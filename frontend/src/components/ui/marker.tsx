import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '@/lib/utils'

const markerVariants = cva('group/marker relative flex w-full items-center gap-2 text-caption text-muted-foreground', {
  variants: {
    variant: {
      default: '',
      separator: 'before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border',
      border: 'rounded-md border border-border bg-surface px-3 py-2',
    },
  },
  defaultVariants: {
    variant: 'default',
  },
})

function Marker({
  className,
  variant = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'div'> &
  VariantProps<typeof markerVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : 'div'

  return (
    <Comp
      data-slot="marker"
      data-variant={variant}
      className={cn(markerVariants({ variant }), className)}
      {...props}
    />
  )
}

function MarkerIcon({ className, ...props }: React.ComponentProps<'span'>) {
  return <span data-slot="marker-icon" aria-hidden="true" className={cn('shrink-0', className)} {...props} />
}

function MarkerContent({ className, ...props }: React.ComponentProps<'span'>) {
  return <span data-slot="marker-content" className={cn('min-w-0 break-words', className)} {...props} />
}

export { Marker, MarkerIcon, MarkerContent, markerVariants }
