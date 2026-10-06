import gsap from 'gsap'
import { tokenDuration, tokenEase, tokenNumber } from './motionTokens.js'

export function openDialog(dialog, reducedMotion = false) {
  if (!dialog || dialog.open) return
  dialog.showModal()
  gsap.killTweensOf(dialog)
  if (reducedMotion) {
    gsap.set(dialog, { opacity: 1, scale: 1, clearProps: 'transform' })
    return
  }
  gsap.fromTo(
    dialog,
    { opacity: 0, scale: tokenNumber('--motion-dialog-scale') },
    {
      opacity: 1,
      scale: 1,
      duration: tokenDuration('--dur-dialog'),
      ease: tokenEase('--ease-gsap-reveal'),
      onComplete: () => gsap.set(dialog, { clearProps: 'opacity,transform' })
    }
  )
}

export function closeDialog(dialog, reducedMotion = false) {
  if (!dialog?.open) return
  gsap.killTweensOf(dialog)
  if (reducedMotion) {
    dialog.close()
    return
  }
  gsap.to(dialog, {
    opacity: 0,
    scale: tokenNumber('--motion-dialog-scale'),
    duration: tokenDuration('--dur-dialog'),
    ease: tokenEase('--ease-gsap-standard'),
    onComplete: () => {
      dialog.close()
      gsap.set(dialog, { clearProps: 'opacity,transform' })
    }
  })
}

export function clearDialogMotion(dialog, showFinal = false) {
  if (!dialog) return
  gsap.killTweensOf(dialog)
  if (showFinal) gsap.set(dialog, { opacity: 1, scale: 1, clearProps: 'transform' })
}
