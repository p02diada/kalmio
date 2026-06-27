import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '@/lib/utils'

function BubbleGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="bubble-group" className={cn('flex min-w-0 flex-col gap-1', className)} {...props} />
}

const bubbleVariants = cva(
  'group/bubble relative flex w-fit min-w-0 max-w-[82%] flex-col rounded-md px-3 py-2 text-compact leading-[var(--text-compact--line-height)]',
  {
    variants: {
      variant: {
        default: 'border border-border bg-surface text-body',
        secondary: 'bg-surface text-body',
        muted: 'border border-border/80 bg-muted/70 text-body',
        tinted: 'border border-assistant-soft bg-assistant-soft/70 text-foreground',
        outline: 'border border-border bg-transparent text-body',
        ghost: 'bg-transparent px-0 py-0 text-body',
        destructive: 'border border-error/30 bg-error-soft text-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

function Bubble({
  variant = 'default',
  align = 'start',
  className,
  ...props
}: React.ComponentProps<'div'> &
  VariantProps<typeof bubbleVariants> & {
    align?: 'start' | 'end'
  }) {
  return (
    <div
      data-slot="bubble"
      data-variant={variant}
      data-align={align}
      className={cn(bubbleVariants({ variant }), className)}
      {...props}
    />
  )
}

function BubbleContent({
  asChild = false,
  className,
  ...props
}: React.ComponentProps<'div'> & {
  asChild?: boolean
}) {
  const Comp = asChild ? Slot : 'div'

  return (
    <Comp
      data-slot="bubble-content"
      className={cn('w-fit max-w-full min-w-0 overflow-hidden break-words whitespace-pre-wrap', className)}
      {...props}
    />
  )
}

function BubbleReactions({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="bubble-reactions"
      className={cn('absolute z-10 flex w-fit items-center justify-center', className)}
      {...props}
    />
  )
}

export { BubbleGroup, Bubble, BubbleContent, BubbleReactions }
