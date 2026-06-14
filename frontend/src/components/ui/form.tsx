import type * as React from 'react'
import { FormProvider, useFormContext, type ControllerProps, type FieldPath, type FieldValues } from 'react-hook-form'

import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export const Form = FormProvider

export function FormItem({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('space-y-2', className)} {...props} />
}

export function FormLabel({ className, ...props }: React.ComponentProps<typeof Label>) {
  return <Label className={className} {...props} />
}

export function FormControl({ ...props }: React.ComponentProps<'div'>) {
  return <div {...props} />
}

export function FormDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props} />
}

export function FormMessage({ className, children, ...props }: React.ComponentProps<'p'>) {
  return (
    <p className={cn('text-sm font-medium text-warning', className)} {...props}>
      {children}
    </p>
  )
}

export function useFormField() {
  return useFormContext()
}

export type FormFieldProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> = ControllerProps<TFieldValues, TName>

