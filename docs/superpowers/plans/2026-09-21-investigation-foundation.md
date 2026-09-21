# Investigation Foundation Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan inline, task-by-task in the existing repository. User has authorized Phase 0/Phase 1; no additional design approval is required for this bounded foundation slice.

**Goal:** 建立可回溯基线并交付不依赖市场领域的不可变 Blob Storage 基础。

**Architecture:** 同仓库通用 `marketpulse.infrastructure.storage` 模块，纯标准库 Protocol/value objects 与本地 adapter 分离。旧流程保持运行，未来 Snapshot、recording、Replay 均消费相同 Port。内容先完整落盘再返回可提交数据库的引用。

**Tech Stack:** Python 3.11–3.13（现有 `>=3.11,<3.14`），hashlib/tempfile/os/pathlib，pytest、ruff、strict mypy；无新生产依赖。

**Spec:** `ARCHITECTURE.md` §5 及 `docs/07-investigation-migration.md` Phase 0/1a。

## Global Constraints

- Local trusted single-operator demo；不新增网络服务或 DB migration。
- 不删除 legacy，不复制第二套工程，不使用 market-specific model/error/config。
- Blob identity = SHA-256(content)，逻辑引用 `blob://sha256/<64 lowercase hex>`。
- 无 delete/update Blob API；相同内容去重，损坏/缺失显式失败。
- Storage filesystem 仅 adapter 访问；未来 DB 存逻辑 ref，不能存绝对路径。
- 临时文件 + fsync + 重新校验 + 同卷原子 no-clobber publication；失败最多 orphan。
- Git 仅提交明确白名单文件，不提交真实 key、DB、报告、recordings 或技能/个人脚本。

## Task 1 — baseline and accepted decisions

Files: `ARCHITECTURE.md`, `docs/07-investigation-migration.md`, `docs/08-phase0-baseline.md`。

- [x] 读取现有模块/测试/config，核对旧验收与真实实现边界。
- [x] 运行离线 pytest/ruff/mypy 和前端 test/lint/build、CLI help、uv build。
- [x] 创建只含白名单文件的原工程 baseline commit；同目录创建基础设施分支。
- [x] 保存已确认合同及 Phase 0 实测结果，明确尚未实施的目标架构。

## Task 2 — immutable blob port and local adapter

Files:
- `src/marketpulse/infrastructure/__init__.py`（通用基础设施包）
- `src/marketpulse/infrastructure/storage/__init__.py`（导出稳定接口）
- `src/marketpulse/infrastructure/storage/models.py`（frozen BlobRef/StoredBlob、安全错误码）
- `src/marketpulse/infrastructure/storage/ports.py`（同步 I/O 协议）
- `src/marketpulse/infrastructure/storage/local.py`（文件访问、原子落盘和校验）
- `tests/unit/test_blob_storage.py`（持久化/去重/并发/故障注入契约）

Interfaces:

```python
BlobRef(sha256: str)  # frozen; strict lowercase hex; uri; from_uri
StoredBlob(ref: BlobRef, size_bytes: int)  # frozen
class BlobStoragePort(Protocol):
    def put_bytes(self, content: bytes) -> StoredBlob: ...
    def put_stream(self, stream: BinaryIO) -> StoredBlob: ...
    def get_bytes(self, ref: BlobRef) -> bytes: ...
    def open_stream(self, ref: BlobRef) -> AbstractContextManager[BinaryIO]: ...
    def exists(self, ref: BlobRef) -> bool: ...
    def verify_hash(self, ref: BlobRef) -> bool: ...
# Constructor only accepts local config; business code never receives OS paths.
LocalContentAddressedBlobStorage(root: Path)
```

- [x] 编写失败测试：相同内容同 ref/单物理 Blob，不同内容不同 ref；重开 adapter 可读取；BytesIO/stream 契约一致；路径格式校验；缺失和篡改失败；已存在损坏目标不被覆盖；部分读取失败无最终 Blob；发布失败清理 temp；并发相同内容只有一个有效对象。

```python
def test_port_round_trip(tmp_path):
    store = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    saved = store.put_bytes(b"source snapshot")
    assert store.put_bytes(b"source snapshot") == saved
    assert LocalContentAddressedBlobStorage(tmp_path / "blobs").get_bytes(saved.ref) == b"source snapshot"
    assert saved.ref.uri.startswith("blob://sha256/")
```

- [x] Run `.venv\Scripts\python.exe -m pytest tests/unit/test_blob_storage.py -q -p no:cacheprovider --basetemp=.codex-tmp/blob-red`；确认 import failure。
- [x] 实现 frozen models/异常与 Protocol，引用拒绝非 SHA 输入；所有外部可见异常只含逻辑引用/安全说明。
- [x] 实现 stream 分块写 temp、flush/fsync、重读验证；目标为 sha256/ab/cd/hash；原子 hard-link no-clobber，FileExists 时验证复用，拒绝损坏覆盖。POSIX 同步目录，Windows 说明耐久性范围。
- [x] 读取在向调用者交付之前验证 hash；缺失、损坏、IO 分开错误码；拒绝 blob key 路径穿越和逃逸符号链接。短暂外部调用者局部磁盘篡改不在本机可信模型内，但下次读取必须能检测损坏。
- [x] Run 相同测试（独立 basetemp）；修复 Windows 前缀竞态后 27 passed、1 Windows symlink skipped。

## Task 3 — architecture boundary, packaging and acceptance

Files: `tests/unit/test_infrastructure_boundary.py`, `README.md`, `docs/09-phase1-storage-acceptance.md`。

- [x] 加入 AST import 边界测试：infrastructure 当前仅依赖标准库/自身，禁止导入现有 market domain/config/services/errors；覆盖 TYPE_CHECKING 导入。
- [x] 测试 0-byte Blob、open_stream 在交付前校验、完整异常消息不包含根目录，模拟 fsync 失败/并发写入、移动 Blob 目录后逻辑 ref 可读。
- [x] 更新 README 迁移状态与 Port 使用示例，明确 snapshot/DB/replay 尚未接入。
- [x] Run 离线 pytest/ruff/mypy；`uv build` 并读取 wheel 成员确认 infrastructure/storage 被打包。
- [x] 保存实测数量、跳过项目、限制及实现文件列表；检查 git diff；基础设施改动作为独立提交交付。

本计划只覆盖 baseline 和 Blob 基础，未把 PG Snapshot round-trip、Replay fixture、审查/执行器等后续测试虚报为通过。接下来的 Phase 1b/2 各自有独立计划与验收。
