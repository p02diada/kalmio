import { QueryClient, QueryClientProvider, useMutation, useQuery } from '@tanstack/react-query'
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowUp,
  BatteryCharging,
  Bot,
  CheckCircle2,
  ClipboardList,
  Home,
  Loader2,
  Menu,
  MapPinned,
  MessageCircle,
  Navigation,
  Plus,
  RotateCcw,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import { A2UIRenderer } from '@/components/a2ui/a2ui-renderer'
import { A2UIShowcasePage } from '@/components/a2ui/a2ui-showcase'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
} from '@/components/ui/sidebar'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { Toaster } from '@/components/ui/sonner'
import {
  clearConversation,
  conversationMessagesQueryKey,
  getConversationMessages,
  sendConversationAction,
  sendConversationMessage,
} from '@/lib/api/conversation'
import type { A2UIBlock } from '@/lib/a2ui/types'
import { cn } from '@/lib/utils'

const queryClient = new QueryClient()
const pendingPromptKey = 'kalmio.pendingPrompt'

const quickPrompts = [
  {
    title: 'Carga urgente',
    description: 'Para decidir una parada ahora.',
    value: 'Necesito cargar ya. Te daré ubicación, batería actual y conector. Si falta algún dato crítico, pregúntame antes de recomendar.',
    icon: Zap,
  },
  {
    title: 'Planificar ruta larga',
    description: 'Ruta, autonomía y paradas cómodas.',
    value: 'Quiero planificar una ruta larga. Te daré origen, destino, batería actual, batería útil, consumo, conector y preferencias de parada.',
    icon: Navigation,
  },
  {
    title: 'Plan al llegar',
    description: 'Hotel, destino o parada de noche.',
    value: 'Quiero planificar dónde cargar al llegar a mi hotel o destino. Si falta la ubicación exacta, pregúntame antes de buscar opciones.',
    icon: MapPinned,
  },
]

const intakeItems = [
  'Ubicación',
  'Batería',
  'Conector',
  'Destino',
  'Urgencia',
] as const

const reassuranceSteps = [
  'Te pediré ubicación, batería y conector si faltan.',
  'Comprobaré ruta y paradas con datos autorizados de carga.',
  'Si no hay datos fiables, no recomendaré una parada.',
] as const

const conversationPhases = [
  'Interpretando tu petición',
  'Comprobando ruta o ubicación',
  'Buscando paradas con carga autorizada',
  'Validando riesgo y próximos pasos',
] as const

const chatScrollPriority = [
  'StationPreviewCard',
  'StationDetailCard',
  'RouteCorridorCard',
  'ActionButtons',
  'StationList',
  'AssistantMessage',
] as const

const navItems = [
  { to: '/', icon: Home, label: 'Inicio' },
  { to: '/chat', icon: MessageCircle, label: 'Chat' },
  { to: '/history', icon: ClipboardList, label: 'Historial' },
] as const

function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })

  if (pathname === '/a2ui') {
    return (
      <div className="app-frame">
        <main className="a2ui-review-main">
          <Outlet />
        </main>
        <Toaster richColors position="top-center" />
      </div>
    )
  }

  return (
    <SidebarProvider className="app-frame">
      <DesktopSidebar pathname={pathname} />
      <SidebarInset className="app-shell">
        <MobileTopBar pathname={pathname} />
        <div className="app-main">
          <Outlet />
        </div>
      </SidebarInset>
      <Toaster richColors position="top-center" />
    </SidebarProvider>
  )
}

function DesktopSidebar({ pathname }: { pathname: string }) {
  const startNewChat = useStartNewChat()

  return (
    <Sidebar collapsible="icon" className="hidden md:flex">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Kalmio">
              <Link to="/" aria-label="Kalmio home">
                <span className="grid size-8 place-items-center rounded-md" aria-hidden="true">
                  <KalmioBrandMark className="size-8" />
                </span>
                <span className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">Kalmio</span>
                  <span className="text-xs text-sidebar-foreground/70">Asistente de viaje</span>
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <Button type="button" variant="outline" className="mx-2 justify-start" onClick={startNewChat}>
          <Plus data-icon="inline-start" aria-hidden="true" />
          Nuevo chat
        </Button>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Viaje</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <DesktopNavItem key={item.to} {...item} isActive={isActivePath(pathname, item.to)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}

function MobileTopBar({ pathname }: { pathname: string }) {
  const startNewChat = useStartNewChat()
  const showNewChat = pathname.startsWith('/chat')

  return (
    <header className="mobile-top-bar">
      <div className="mobile-top-actions mobile-top-actions-left">
        <Sheet>
          <SheetTrigger asChild>
            <Button type="button" variant="ghost" size="icon" className="liquid-icon-button" aria-label="Abrir menú">
              <Menu aria-hidden="true" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="mobile-menu-sheet">
            <SheetHeader className="mobile-menu-header">
              <SheetTitle className="flex min-w-0 items-center gap-2 text-base">
                <span className="grid size-8 place-items-center rounded-md" aria-hidden="true">
                  <KalmioBrandMark className="size-8" />
                </span>
                <span className="font-semibold">Kalmio</span>
              </SheetTitle>
              <SheetDescription className="sr-only">
                Navegación principal de Kalmio.
              </SheetDescription>
            </SheetHeader>

            <div className="mobile-menu-section">
              <nav className="flex flex-col" aria-label="Navegación principal">
                {navItems.map((item) => (
                  <MobileMenuItem key={item.to} {...item} isActive={isActivePath(pathname, item.to)} />
                ))}
              </nav>
            </div>

          </SheetContent>
        </Sheet>
      </div>

      {showNewChat ? (
        <div className="mobile-top-actions mobile-top-actions-right">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="liquid-icon-button"
            aria-label="Nuevo chat"
            onClick={startNewChat}
          >
            <Plus aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </header>
  )
}

function MobileMenuItem({
  to,
  icon: Icon,
  label,
  isActive,
}: {
  to: string
  icon: LucideIcon
  label: string
  isActive: boolean
}) {
  return (
    <SheetClose asChild>
      <Link
        to={to}
        className={cn('mobile-menu-link', isActive && 'mobile-menu-link-active')}
      >
        <Icon aria-hidden="true" />
        <span>{label}</span>
      </Link>
    </SheetClose>
  )
}

function KalmioBrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo-mark.svg"
      alt=""
      aria-hidden="true"
      className={cn('block', className)}
    />
  )
}

function DesktopNavItem({
  to,
  icon: Icon,
  label,
  isActive,
}: {
  to: string
  icon: LucideIcon
  label: string
  isActive: boolean
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={isActive} tooltip={label}>
        <Link to={to}>
          <Icon aria-hidden="true" />
          <span>{label}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

function isActivePath(pathname: string, to: string) {
  return to === '/' ? pathname === '/' : pathname.startsWith(to)
}

function useStartNewChat() {
  const navigate = useNavigate()

  return useCallback(() => {
    sessionStorage.removeItem(pendingPromptKey)
    queryClient.removeQueries({ queryKey: conversationMessagesQueryKey })
    navigate({ to: '/chat' })
    void clearConversation()
      .catch(() => undefined)
      .finally(() => {
        queryClient.invalidateQueries({ queryKey: conversationMessagesQueryKey })
      })
  }, [navigate])
}

function HomePage() {
  const navigate = useNavigate()
  const [intent, setIntent] = useState('')
  const trimmedIntent = intent.trim()

  const startChat = (value: string) => {
    const text = value.trim()
    if (!text) {
      return
    }
    sessionStorage.setItem(pendingPromptKey, text)
    navigate({ to: '/chat' })
  }

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 pt-2">
        <p className="font-mono text-xs leading-4 text-muted-foreground">Viaja sin ansiedad de carga</p>
        <h1 className="max-w-hero-width text-balance text-hero font-semibold leading-none tracking-display text-foreground">Cuenta tu ruta o urgencia</h1>
        <p className="text-pretty text-base leading-7 text-body">
          Kalmio preguntará lo que falte antes de recomendar. No inventa disponibilidad, precios ni estaciones.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          startChat(intent)
        }}
      >
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="home-intent" className="sr-only">Describe lo que necesitas</FieldLabel>
            <InputGroup className="h-16 rounded-md bg-surface">
              <InputGroupInput
                id="home-intent"
                value={intent}
                onChange={(event) => setIntent(event.target.value)}
                placeholder="Estoy en..., 18%, CCS2..."
                className="h-14 text-input"
              />
              <InputGroupAddon align="inline-end">
                <InputGroupButton type="submit" size="icon-sm" className="size-11 rounded-full" aria-label="Abrir chat" disabled={!trimmedIntent}>
                  <ArrowUp aria-hidden="true" />
                </InputGroupButton>
              </InputGroupAddon>
            </InputGroup>
            <FieldDescription>
              {trimmedIntent
                ? 'Revisa el mensaje. Al enviarlo, Kalmio abrirá el chat y pedirá lo que falte.'
                : 'No hace falta tenerlo todo. Empieza con lo que sepas.'}
            </FieldDescription>
          </Field>
        </FieldGroup>
      </form>

      <div className="flex flex-wrap gap-2" aria-label="Datos útiles para Kalmio">
        {intakeItems.map((item) => (
          <span key={item} className="rounded-full bg-muted px-2.5 py-1 text-caption font-medium leading-4 text-body">
            {item}
          </span>
        ))}
      </div>

      <div className="flex flex-col gap-2.5">
        <div className="flex flex-col gap-1">
          <p className="text-compact font-semibold text-foreground">Inicio guiado</p>
          <p className="text-sm leading-5 text-muted-foreground">Elige una guía para abrir el chat con el primer mensaje preparado.</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {quickPrompts.map((prompt) => {
            const Icon = prompt.icon
            return (
              <Button
                key={prompt.title}
                type="button"
                variant="outline"
                className="h-auto w-full justify-start gap-3 whitespace-normal rounded-md px-3 py-3 text-left"
                onClick={() => startChat(prompt.value)}
              >
                <Icon data-icon="inline-start" aria-hidden="true" />
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-compact font-semibold">{prompt.title}</span>
                  <span className="text-xs font-normal leading-4 text-muted-foreground">{prompt.description}</span>
                </span>
              </Button>
            )
          })}
        </div>
      </div>

      <div className="rounded-md bg-muted p-3">
        <p className="text-compact font-semibold text-foreground">Antes de recomendar</p>
        <ol className="mt-2 flex flex-col gap-2">
          {reassuranceSteps.map((step, index) => (
            <li key={step} className="flex gap-2 text-sm leading-5 text-body">
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface font-mono text-[0.7rem] font-semibold text-foreground">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>

    </section>
  )
}

function ChatPage() {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const [phaseIndex, setPhaseIndex] = useState(0)
  const [retryText, setRetryText] = useState<string | null>(null)
  const [pendingUserBlock, setPendingUserBlock] = useState<A2UIBlock | null>(null)
  const sentInitialPrompt = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const latestRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const previousBlockIdsRef = useRef<Set<string>>(new Set())
  const messagesQuery = useQuery({
    queryKey: conversationMessagesQueryKey,
    queryFn: getConversationMessages,
  })
  const renderedBlocks = useMemo(() => {
    if (messagesQuery.data) {
      return pendingUserBlock
        ? [...messagesQuery.data.blocks, pendingUserBlock]
        : messagesQuery.data.blocks
    }
    return pendingUserBlock ? [pendingUserBlock] : []
  }, [messagesQuery.data, pendingUserBlock])
  const blockCount = renderedBlocks.length
  const blockSignature = renderedBlocks.map((block) => `${block.id}:${block.type}`).join('|')
  const sendMutation = useMutation({
    mutationFn: sendConversationMessage,
    onSuccess: (data) => {
      queryClient.setQueryData(conversationMessagesQueryKey, data)
      setPendingUserBlock(null)
    },
  })
  const actionMutation = useMutation({
    mutationFn: sendConversationAction,
    onSuccess: (data) => {
      queryClient.setQueryData(conversationMessagesQueryKey, data)
    },
  })
  const clearMutation = useMutation({
    mutationFn: clearConversation,
    onSuccess: () => {
      setPendingUserBlock(null)
      queryClient.invalidateQueries({ queryKey: conversationMessagesQueryKey })
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : 'No se pudo limpiar la conversación.')
    },
  })

  const sendText = useCallback((value: string) => {
    const text = value.trim()
    if (!text || isSending) {
      return
    }
    setDraft('')
    setError(null)
    setRetryText(null)
    setPendingUserBlock({
      id: `pending-user-${Date.now()}`,
      type: 'UserMessage',
      version: 1,
      props: { text },
    })
    setIsSending(true)
    setPhaseIndex(0)
    sendMutation.mutateAsync(text)
      .catch((mutationError) => {
        setError(mutationError instanceof Error ? mutationError.message : 'No se pudo enviar el mensaje.')
        setRetryText(text)
      })
      .finally(() => {
        setIsSending(false)
      })
  }, [isSending, sendMutation])

  const sendA2UIEvent = useCallback((name: string, context: Record<string, unknown> = {}, sourceComponentId?: string) => {
    const actionName = name.trim()
    if (!actionName || isSending) {
      return
    }
    setError(null)
    setRetryText(null)
    setIsSending(true)
    setPhaseIndex(0)
    actionMutation.mutateAsync({
      name: actionName,
      context,
      sourceComponentId,
      surfaceId: messagesQuery.data?.surfaceId,
    })
      .catch((mutationError) => {
        setError(mutationError instanceof Error ? mutationError.message : 'No se pudo enviar la acción.')
      })
      .finally(() => {
        setIsSending(false)
      })
  }, [actionMutation, isSending, messagesQuery.data?.surfaceId])

  useEffect(() => {
    if (sentInitialPrompt.current) {
      return
    }
    const pending = sessionStorage.getItem(pendingPromptKey)
    if (!pending) {
      return
    }
    const timer = window.setTimeout(() => {
      if (sentInitialPrompt.current) {
        return
      }
      sentInitialPrompt.current = true
      sessionStorage.removeItem(pendingPromptKey)
      sendText(pending)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [sendText])

  useEffect(() => {
    if (!isSending) {
      return
    }
    const timer = window.setInterval(() => {
      setPhaseIndex((current) => Math.min(current + 1, conversationPhases.length - 1))
    }, 1800)
    return () => window.clearInterval(timer)
  }, [isSending])

  useEffect(() => {
    const previousBlockIds = previousBlockIdsRef.current
    const newBlocks = renderedBlocks.filter((block) => !previousBlockIds.has(block.id))
    const scrollTargetBlockId = selectChatScrollTarget(newBlocks, isSending)
    previousBlockIdsRef.current = new Set(renderedBlocks.map((block) => block.id))

    if (!blockCount && !isSending && !error) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      const target = scrollTargetBlockId ? findA2UIBlockElement(scrollRef.current, scrollTargetBlockId) : latestRef.current
      if (typeof target?.scrollIntoView === 'function') {
        target.scrollIntoView({ block: scrollTargetBlockId ? 'start' : 'end', behavior: 'smooth' })
      }
      if (!isSending) {
        composerRef.current?.focus({ preventScroll: true })
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [blockCount, blockSignature, isSending, error, renderedBlocks])

  return (
    <section className="chat-page">
      <h1 className="sr-only">Chat</h1>

      <div ref={scrollRef} className="chat-scroll" aria-live="polite">
        {messagesQuery.isPending ? <ConversationSkeleton /> : null}
        {!messagesQuery.isPending && renderedBlocks.length === 0 && !isSending && !error ? <ChatEmptyState /> : null}
        {renderedBlocks.length > 0 ? (
          <A2UIRenderer blocks={renderedBlocks} onChipClick={sendText} onActionEvent={sendA2UIEvent} />
        ) : null}
        {isSending ? <ConversationProgress phaseIndex={phaseIndex} /> : null}
        {error ? <InlineError message={error} onRetry={retryText ? () => sendText(retryText) : undefined} /> : null}
        <div ref={latestRef} className="h-px" tabIndex={-1} aria-hidden="true" />
      </div>

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          sendText(draft)
        }}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-9 shrink-0 rounded-full"
          aria-label="Reiniciar chat"
          onClick={() => clearMutation.mutate()}
          disabled={clearMutation.isPending}
        >
          <RotateCcw className="size-4" aria-hidden="true" />
        </Button>
        <Textarea
          ref={composerRef}
          aria-label="Mensaje para Kalmio"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ruta, batería o destino"
          rows={1}
          className="chat-composer-input border-0 px-2 shadow-none focus-visible:outline-none"
        />
        <Button type="submit" size="icon" className="size-9 shrink-0 rounded-full md:w-auto md:px-3" aria-label="Enviar" disabled={isSending || draft.trim().length === 0}>
          <ArrowUp className="size-4" aria-hidden="true" />
          <span className="hidden md:inline">Enviar</span>
        </Button>
      </form>
    </section>
  )
}

function selectChatScrollTarget(blocks: A2UIBlock[], isSending: boolean) {
  if (blocks.length === 0) {
    return null
  }
  if (isSending && blocks.every((block) => block.type === 'UserMessage')) {
    return blocks.at(-1)?.id ?? null
  }
  for (const blockType of chatScrollPriority) {
    const match = blocks.find((block) => block.type === blockType)
    if (match) {
      return match.id
    }
  }
  return blocks.find((block) => block.type !== 'UserMessage')?.id ?? blocks.at(-1)?.id ?? null
}

function findA2UIBlockElement(container: HTMLElement | null, blockId: string) {
  if (!container) {
    return null
  }
  return Array.from(container.querySelectorAll<HTMLElement>('[data-a2ui-block-id]')).find(
    (element) => element.dataset.a2uiBlockId === blockId,
  ) ?? null
}

function ChatEmptyState() {
  return (
    <div className="chat-empty">
      <p className="text-compact font-semibold text-foreground">Cuéntame lo esencial.</p>
      <p className="text-sm leading-5 text-body">Ruta, batería, conector, hotel o preferencia de parada. Si falta algo crítico, te lo pediré antes de recomendar.</p>
    </div>
  )
}

function HistoryPage() {
  return (
    <section className="flex flex-col gap-4">
      <PageHeading title="Historial" text="Sesiones de chat para continuar decisiones de carga sin repetir contexto." />
      <Card>
        <CardContent className="flex items-start gap-3 p-4">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted text-foreground">
            <ClipboardList className="size-5" aria-hidden="true" />
          </span>
          <div className="flex flex-col gap-2">
            <h2 className="font-semibold text-foreground">Todavía no hay sesiones guardadas</h2>
            <p className="text-sm leading-6 text-muted-foreground">
              Ahora puedes continuar la conversación activa. Cuando el historial persistente esté disponible, cada chat aparecerá aquí con su último estado.
            </p>
            <Button asChild variant="outline" className="w-fit">
              <Link to="/chat">Abrir chat</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}

type ThemePreview = {
  name: string
  stance: string
  use: string
  visual?: 'trace' | 'agentic-trace'
  variables: Record<string, string>
}

const themePreviews: ThemePreview[] = [
  {
    name: 'Agentic Signal',
    stance: 'La IA se nota sin convertir la app en una demo.',
    use: 'Referencia AI: más expresiva, útil para medir cuánta presencia agente tolera la app.',
    variables: {
      '--font-sans': '"Geist", "Inter", ui-sans-serif, system-ui, sans-serif',
      '--font-mono': '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
      '--color-background': 'oklch(97.8% 0.009 235)',
      '--color-surface': 'oklch(100% 0 0)',
      '--color-foreground': 'oklch(18% 0.018 250)',
      '--color-body': 'oklch(38% 0.025 245)',
      '--color-muted': 'oklch(95.8% 0.017 240)',
      '--color-muted-strong': 'oklch(92.2% 0.024 240)',
      '--color-muted-foreground': 'oklch(45% 0.029 245)',
      '--color-border': 'oklch(88.4% 0.023 240)',
      '--color-border-strong': 'oklch(61% 0.038 245)',
      '--color-primary': 'oklch(31% 0.09 250)',
      '--color-primary-foreground': 'oklch(99% 0.003 250)',
      '--color-primary-soft': 'oklch(92.2% 0.04 250)',
      '--color-link': 'oklch(56% 0.19 240)',
      '--color-link-soft': 'oklch(91% 0.055 240)',
      '--color-warning': 'oklch(72% 0.17 70)',
      '--color-warning-soft': 'oklch(93.5% 0.061 76)',
      '--color-error': 'oklch(58% 0.23 28)',
      '--color-error-soft': 'oklch(91.5% 0.052 20)',
      '--color-route': 'oklch(57% 0.18 235)',
      '--color-route-soft': 'oklch(90.5% 0.059 235)',
      '--color-assistant': 'oklch(52% 0.22 315)',
      '--color-assistant-soft': 'oklch(91% 0.062 315)',
      '--color-cyan': 'oklch(76% 0.19 145)',
      '--radius-sm': '0.625rem',
      '--radius-md': '0.75rem',
      '--radius-lg': '1rem',
      '--radius-full': '9999px',
      '--spacing-app-width': '430px',
      '--spacing-app-height': '880px',
      '--spacing-hero-width': '13ch',
      '--spacing-chat-panel': 'calc(100svh - 9rem)',
      '--text-caption': '0.75rem',
      '--text-caption--line-height': '1rem',
      '--text-compact': '0.875rem',
      '--text-compact--line-height': '1.28rem',
      '--text-input': '0.975rem',
      '--text-input--line-height': '1.3rem',
      '--text-hero': '2.55rem',
      '--text-hero--line-height': '1',
      '--tracking-display': '-0.035em',
    },
  },
  {
    name: 'Signal Trace',
    stance: 'Wow sobrio: la inteligencia aparece como traza verificable de ruta, riesgo y siguiente acción.',
    use: 'Referencia trazable: prioriza ruta, reserva y confianza sobre presencia AI explícita.',
    visual: 'trace',
    variables: {
      '--font-sans': '"Geist", "Inter", ui-sans-serif, system-ui, sans-serif',
      '--font-mono': '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
      '--color-background': 'oklch(97.8% 0.008 225)',
      '--color-surface': 'oklch(99.8% 0.002 225)',
      '--color-foreground': 'oklch(18% 0.018 245)',
      '--color-body': 'oklch(36% 0.026 245)',
      '--color-muted': 'oklch(95.4% 0.014 225)',
      '--color-muted-strong': 'oklch(91.8% 0.02 225)',
      '--color-muted-foreground': 'oklch(42% 0.028 245)',
      '--color-border': 'oklch(87.8% 0.02 225)',
      '--color-border-strong': 'oklch(58% 0.04 235)',
      '--color-primary': 'oklch(25% 0.055 245)',
      '--color-primary-foreground': 'oklch(99% 0.003 250)',
      '--color-primary-soft': 'oklch(92.5% 0.028 245)',
      '--color-link': 'oklch(56% 0.18 225)',
      '--color-link-soft': 'oklch(90.8% 0.056 225)',
      '--color-warning': 'oklch(76% 0.15 76)',
      '--color-warning-soft': 'oklch(94% 0.056 78)',
      '--color-error': 'oklch(58% 0.23 28)',
      '--color-error-soft': 'oklch(91.5% 0.052 20)',
      '--color-route': 'oklch(56% 0.18 225)',
      '--color-route-soft': 'oklch(90.8% 0.056 225)',
      '--color-assistant': 'oklch(36% 0.08 260)',
      '--color-assistant-soft': 'oklch(91.5% 0.035 260)',
      '--color-cyan': 'oklch(69% 0.16 165)',
      '--radius-sm': '0.625rem',
      '--radius-md': '0.75rem',
      '--radius-lg': '0.875rem',
      '--radius-full': '9999px',
      '--spacing-app-width': '430px',
      '--spacing-app-height': '880px',
      '--spacing-hero-width': '13ch',
      '--spacing-chat-panel': 'calc(100svh - 9rem)',
      '--text-caption': '0.75rem',
      '--text-caption--line-height': '1rem',
      '--text-compact': '0.875rem',
      '--text-compact--line-height': '1.28rem',
      '--text-input': '0.975rem',
      '--text-input--line-height': '1.3rem',
      '--text-hero': '2.5rem',
      '--text-hero--line-height': '1',
      '--tracking-display': '-0.03em',
    },
  },
  {
    name: 'Agentic Trace',
    stance: 'Híbrido: traza verificable como base, con señal agente solo donde ayuda a leer la decisión.',
    use: 'Candidata principal: conserva confianza y añade una capa AI reconocible pero contenida.',
    visual: 'agentic-trace',
    variables: {
      '--font-sans': '"Geist", "Inter", ui-sans-serif, system-ui, sans-serif',
      '--font-mono': '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
      '--color-background': 'oklch(97.7% 0.009 230)',
      '--color-surface': 'oklch(99.8% 0.002 230)',
      '--color-foreground': 'oklch(18% 0.018 248)',
      '--color-body': 'oklch(36.5% 0.026 245)',
      '--color-muted': 'oklch(95.3% 0.015 230)',
      '--color-muted-strong': 'oklch(91.6% 0.022 232)',
      '--color-muted-foreground': 'oklch(42.5% 0.029 246)',
      '--color-border': 'oklch(87.7% 0.021 230)',
      '--color-border-strong': 'oklch(58.5% 0.041 238)',
      '--color-primary': 'oklch(27% 0.07 248)',
      '--color-primary-foreground': 'oklch(99% 0.003 250)',
      '--color-primary-soft': 'oklch(92.4% 0.034 248)',
      '--color-link': 'oklch(56% 0.18 228)',
      '--color-link-soft': 'oklch(90.8% 0.056 228)',
      '--color-warning': 'oklch(75% 0.16 74)',
      '--color-warning-soft': 'oklch(93.8% 0.058 78)',
      '--color-error': 'oklch(58% 0.23 28)',
      '--color-error-soft': 'oklch(91.5% 0.052 20)',
      '--color-route': 'oklch(56% 0.18 228)',
      '--color-route-soft': 'oklch(90.8% 0.056 228)',
      '--color-assistant': 'oklch(50% 0.19 305)',
      '--color-assistant-soft': 'oklch(91.2% 0.052 305)',
      '--color-cyan': 'oklch(72% 0.17 155)',
      '--radius-sm': '0.625rem',
      '--radius-md': '0.75rem',
      '--radius-lg': '0.875rem',
      '--radius-full': '9999px',
      '--spacing-app-width': '430px',
      '--spacing-app-height': '880px',
      '--spacing-hero-width': '13ch',
      '--spacing-chat-panel': 'calc(100svh - 9rem)',
      '--text-caption': '0.75rem',
      '--text-caption--line-height': '1rem',
      '--text-compact': '0.875rem',
      '--text-compact--line-height': '1.28rem',
      '--text-input': '0.975rem',
      '--text-input--line-height': '1.3rem',
      '--text-hero': '2.5rem',
      '--text-hero--line-height': '1',
      '--tracking-display': '-0.03em',
    },
  },
]

const previewTokens = [
  '--color-background',
  '--color-surface',
  '--color-foreground',
  '--color-primary',
  '--color-route',
  '--color-assistant',
  '--color-cyan',
  '--color-warning',
  '--color-error',
  '--radius-md',
  '--text-hero',
  '--tracking-display',
] as const

function DesignSystemPreviewPage() {
  return (
    <section className="design-system-page flex w-full max-w-none flex-col gap-6">
      <PageHeading
        title="Sistemas visuales"
        text="Comparativa local de variables Tailwind/shadcn para Kalmio. Cada bloque redefine las mismas custom properties sin cambiar todavía el tema global."
      />
      <div className="grid gap-5 xl:grid-cols-2">
        {themePreviews.map((theme) => (
          <ThemePreviewPanel key={theme.name} theme={theme} />
        ))}
      </div>
    </section>
  )
}

function ThemePreviewPanel({ theme }: { theme: ThemePreview }) {
  return (
    <article
      className={cn(
        'design-preview overflow-hidden rounded-lg border border-border bg-background text-foreground',
        theme.visual && `design-preview-${theme.visual}`,
      )}
      style={theme.variables as CSSProperties}
    >
      <div className="flex flex-col gap-4 border-b border-border bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex max-w-xl flex-col gap-1">
            <h2 className="text-xl font-semibold tracking-normal">{theme.name}</h2>
            <p className="text-sm leading-6 text-body">{theme.stance}</p>
          </div>
          <span className="rounded-full bg-primary-soft px-3 py-1 text-caption font-semibold leading-4 text-primary">
            {theme.use}
          </span>
        </div>
        <ThemeTokenStrip theme={theme} />
      </div>
      <div className="grid gap-4 p-4">
        <ThemePhonePreview />
        <ThemeDecisionPreview />
      </div>
    </article>
  )
}

function ThemeTokenStrip({ theme }: { theme: ThemePreview }) {
  return (
    <div className="design-token-strip grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {previewTokens.map((token) => {
        const value = theme.variables[token]
        const isColor = token.startsWith('--color')

        return (
          <div key={token} className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5">
            {isColor ? (
              <span
                className="size-5 shrink-0 rounded-full border border-border"
                style={{ background: value }}
                aria-hidden="true"
              />
            ) : null}
            <div className="min-w-0">
              <p className="truncate font-mono text-[0.68rem] leading-3 text-muted-foreground">{token}</p>
              <p className="truncate font-mono text-[0.68rem] leading-3 text-foreground">{value}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ThemePhonePreview() {
  return (
    <div className="design-phone-preview mx-auto flex w-full max-w-[24rem] flex-col gap-4 rounded-lg border border-border bg-background p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="grid size-9 place-items-center rounded-md" aria-hidden="true">
            <KalmioBrandMark className="size-9" />
          </span>
          <div>
            <p className="text-sm font-semibold leading-5">Kalmio</p>
            <p className="text-caption font-medium leading-4 text-muted-foreground">Asistente de viaje</p>
          </div>
        </div>
        <span className="rounded-full bg-muted px-2.5 py-1 text-caption font-semibold leading-4 text-body">18%</span>
      </div>

      <div className="flex flex-col gap-3">
        <p className="font-mono text-caption leading-4 text-muted-foreground">Viaja sin ansiedad de carga</p>
        <h3 className="max-w-hero-width text-hero font-semibold leading-none tracking-display text-foreground">
          Cuenta tu ruta o urgencia
        </h3>
        <p className="text-sm leading-6 text-body">
          El agente preguntará lo que falte antes de recomendar una parada.
        </p>
      </div>

      <div className="flex items-center gap-2 rounded-md border border-border bg-surface p-2">
        <span className="min-w-0 flex-1 truncate text-input leading-5 text-muted-foreground">Estoy en A-2, 18%, CCS2...</span>
        <Button type="button" size="icon" className="size-9 shrink-0">
          <ArrowUp aria-hidden="true" />
        </Button>
      </div>

      <div className="grid gap-2">
        <button className="flex items-center gap-3 rounded-md border border-border bg-surface p-3 text-left transition-colors hover:bg-muted">
          <Zap aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-compact font-semibold leading-5">Carga urgente</span>
            <span className="block text-caption leading-4 text-muted-foreground">Decidir una parada ahora.</span>
          </span>
        </button>
        <button className="flex items-center gap-3 rounded-md border border-border bg-surface p-3 text-left transition-colors hover:bg-muted">
          <Navigation aria-hidden="true" />
          <span className="min-w-0">
            <span className="block text-compact font-semibold leading-5">Planificar ruta larga</span>
            <span className="block text-caption leading-4 text-muted-foreground">Ruta, autonomía y paradas cómodas.</span>
          </span>
        </button>
      </div>
    </div>
  )
}

function ThemeDecisionPreview() {
  return (
    <div className="design-decision-preview flex flex-col gap-3">
      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-md bg-assistant-soft text-assistant">
              <Bot aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold leading-5">Necesito confirmar un dato</p>
              <p className="text-caption font-medium leading-4 text-muted-foreground">Antes de buscar estaciones autorizadas.</p>
            </div>
          </div>
          <p className="text-sm leading-6 text-body">
            ¿Tu conector es CCS2 y quieres priorizar una parada con cafetería?
          </p>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-full bg-muted px-2.5 py-1 text-caption font-semibold leading-4 text-body">CCS2</span>
            <span className="rounded-full bg-muted px-2.5 py-1 text-caption font-semibold leading-4 text-body">Cafetería</span>
            <span className="rounded-full bg-muted px-2.5 py-1 text-caption font-semibold leading-4 text-body">10% reserva</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-md bg-route-soft text-route">
                <BatteryCharging aria-hidden="true" />
              </span>
              <div>
                <p className="text-sm font-semibold leading-5">Parada recomendada</p>
                <p className="text-caption font-medium leading-4 text-muted-foreground">Área A-2 · 12 km de desvío</p>
              </div>
            </div>
            <span className="rounded-full bg-warning-soft px-2.5 py-1 text-caption font-bold leading-4 text-foreground">4/10 puestos</span>
          </div>
          <div className="grid gap-2 rounded-md bg-muted p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Potencia máx.</span>
              <span className="font-semibold">150 kW</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Llegada estimada</span>
              <span className="font-semibold">11%</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Confianza</span>
              <span className="font-semibold">Media</span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="button" className="flex-1">
              <CheckCircle2 aria-hidden="true" />
              Usar parada
            </Button>
            <Button type="button" variant="outline" className="flex-1">
              Ver mapa
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ConversationProgress({ phaseIndex }: { phaseIndex: number }) {
  const progress = ((phaseIndex + 1) / conversationPhases.length) * 100

  return (
    <Card aria-live="polite">
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          {conversationPhases[phaseIndex]}
        </div>
        <Progress value={progress} aria-label="Progreso de la comprobación" />
        <ol className="grid gap-2 text-xs leading-5 text-muted-foreground">
          {conversationPhases.map((phase, index) => (
            <li key={phase} className={cn('flex items-center gap-2', index <= phaseIndex && 'text-foreground')}>
              <span className={cn('size-1.5 rounded-full bg-border', index <= phaseIndex && 'bg-primary')} aria-hidden="true" />
              {phase}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}

function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm leading-6">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-1 size-4 shrink-0 text-foreground" aria-hidden="true" />
        <span>{message}</span>
      </div>
      {onRetry ? (
        <Button type="button" variant="outline" size="sm" className="w-fit bg-surface" onClick={onRetry}>
          Reintentar
        </Button>
      ) : null}
    </div>
  )
}

function ConversationSkeleton() {
  return (
    <Card aria-live="polite">
      <CardContent className="space-y-3 pt-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-10 w-full" />
      </CardContent>
    </Card>
  )
}

function PageHeading({ title, text }: { title: string; text: string }) {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold tracking-normal">{title}</h1>
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{text}</p>
    </div>
  )
}

const rootRoute = createRootRoute({
  component: AppShell,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
})

const chatRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/chat',
  component: ChatPage,
})

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/history',
  component: HistoryPage,
})

const a2uiRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/a2ui',
  component: A2UIShowcasePage,
})

const designSystemRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/design-system',
  component: DesignSystemPreviewPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  chatRoute,
  historyRoute,
  a2uiRoute,
  designSystemRoute,
])

const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
