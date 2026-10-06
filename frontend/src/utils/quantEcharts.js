import { init, use } from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])
export const mountChart = element => init(element, null, { renderer: 'canvas' })
