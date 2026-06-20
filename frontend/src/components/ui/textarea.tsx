import type * as React from 'react'

import { cn } from '@/lib/utils'

export function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      className={cn(
        'flex min-h-20 w-full resize-none rounded-sm border border-border bg-surface px-3 py-2 text-sm leading-6 transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/12 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-error aria-invalid:ring-2 aria-invalid:ring-error/15',
        className,
      )}
      {...props}
    />
  )
}
