import { cn } from '@/lib/utils'

export function KalmioBrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo-mark.svg"
      alt=""
      aria-hidden="true"
      className={cn('block', className)}
    />
  )
}
