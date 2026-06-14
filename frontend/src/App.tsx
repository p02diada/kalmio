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
  Activity,
  AlertTriangle,
  ArrowUp,
  ClipboardList,
  Home,
  Loader2,
  MapPinned,
  MessageCircle,
  Navigation,
  RotateCcw,
  Settings,
  UserRound,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { A2UIRenderer } from '@/components/a2ui/a2ui-renderer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
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
import { Textarea } from '@/components/ui/textarea'
import { Toaster } from '@/components/ui/sonner'
import {
  authQueryKey,
  getCurrentUser,
  login,
  logout,
  register,
  type AuthCredentials,
} from '@/lib/api/auth'
import {
  clearConversation,
  conversationMessagesQueryKey,
  getConversationMessages,
  sendConversationMessage,
} from '@/lib/api/conversation'
import { listRoutePlans, type RoutePlanResponse } from '@/lib/api/route-plan'
import { cn } from '@/lib/utils'

const queryClient = new QueryClient()
const routePlansQueryKey = ['route-plans'] as const
const pendingPromptKey = 'kalmio.pendingPrompt'

const defaultAuthForm: AuthCredentials = {
  email: '',
  password: '',
}

const quickPrompts = [
  {
    title: 'Carga urgente',
    description: 'Para cuando necesitas decidir ahora.',
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
    title: 'Cargar al llegar',
    description: 'Hotel, destino o parada de noche.',
    value: 'Quiero cargar al llegar a mi hotel o destino. Si falta la ubicación exacta, pregúntame antes de buscar opciones.',
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
  'Comprobaré ruta y cargadores con fuentes autorizadas.',
  'Si no hay datos fiables, no recomendaré una estación.',
] as const

const navItems = [
  { to: '/', icon: Home, label: 'Inicio' },
  { to: '/chat', icon: MessageCircle, label: 'Chat' },
  { to: '/activity', icon: Activity, label: 'Planes' },
  { to: '/settings', icon: Settings, label: 'Cuenta' },
] as const

function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })

  return (
    <SidebarProvider className="app-frame">
      <DesktopSidebar pathname={pathname} />
      <SidebarInset className="app-shell">
        <header className="mobile-app-header">
          <div className="flex items-center justify-between gap-3">
            <Link to="/" className="flex items-baseline gap-1" aria-label="Kalmio home">
              <span className="text-sm font-semibold leading-none text-foreground">Kalmio</span>
              <span className="font-mono text-xs leading-none text-muted-foreground">EV</span>
            </Link>
            <Link to="/settings" className="grid size-8 place-items-center rounded-full border border-border bg-surface text-foreground" aria-label="Cuenta">
              <UserRound className="size-4" aria-hidden="true" />
            </Link>
          </div>
        </header>

        <div className="app-main">
          <Outlet />
        </div>

        <nav className="mobile-bottom-nav" aria-label="Navegación principal">
          <div className="mx-auto grid max-w-app-width grid-cols-4 gap-1">
            {navItems.map((item) => (
              <MobileNavItem key={item.to} {...item} isActive={isActivePath(pathname, item.to)} />
            ))}
          </div>
        </nav>
      </SidebarInset>
      <Toaster richColors position="top-center" />
    </SidebarProvider>
  )
}

function DesktopSidebar({ pathname }: { pathname: string }) {
  return (
    <Sidebar collapsible="icon" className="hidden md:flex">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Kalmio">
              <Link to="/" aria-label="Kalmio home">
                <span className="grid size-8 place-items-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
                  <MapPinned aria-hidden="true" />
                </span>
                <span className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">Kalmio</span>
                  <span className="text-xs text-sidebar-foreground/70">EV assistant</span>
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Viaje</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.slice(0, 3).map((item) => (
                <DesktopNavItem key={item.to} {...item} isActive={isActivePath(pathname, item.to)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <DesktopNavItem {...navItems[3]} isActive={isActivePath(pathname, navItems[3].to)} />
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
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

function MobileNavItem({
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
    <Link
      to={to}
      className={cn('app-nav-item', isActive && 'app-nav-item-active')}
    >
      <Icon className="size-4" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  )
}

function isActivePath(pathname: string, to: string) {
  return to === '/' ? pathname === '/' : pathname.startsWith(to)
}

function HomePage() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
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

  const selectPrompt = (value: string) => {
    setIntent(value)
    window.requestAnimationFrame(() => inputRef.current?.focus())
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
                ref={inputRef}
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
          <p className="text-sm leading-5 text-muted-foreground">Elige una guía, revisa el texto y envíalo cuando esté listo.</p>
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
                onClick={() => selectPrompt(prompt.value)}
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
  const sentInitialPrompt = useRef(false)
  const messagesQuery = useQuery({
    queryKey: conversationMessagesQueryKey,
    queryFn: getConversationMessages,
  })
  const sendMutation = useMutation({
    mutationFn: sendConversationMessage,
    onSuccess: (data) => {
      queryClient.setQueryData(conversationMessagesQueryKey, data)
    },
  })
  const clearMutation = useMutation({
    mutationFn: clearConversation,
    onSuccess: () => {
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
    setIsSending(true)
    sendMutation.mutateAsync(text)
      .catch((mutationError) => {
        setError(mutationError instanceof Error ? mutationError.message : 'No se pudo enviar el mensaje.')
      })
      .finally(() => {
        setIsSending(false)
      })
  }, [isSending, sendMutation])

  useEffect(() => {
    if (sentInitialPrompt.current) {
      return
    }
    const pending = sessionStorage.getItem(pendingPromptKey)
    if (!pending) {
      return
    }
    sentInitialPrompt.current = true
    sessionStorage.removeItem(pendingPromptKey)
    const timer = window.setTimeout(() => sendText(pending), 0)
    return () => window.clearTimeout(timer)
  }, [sendText])

  return (
    <section className="flex min-h-chat-panel flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-normal">Chat</h1>
          <p className="text-sm leading-6 text-muted-foreground">El backend decide qué aclarar, qué herramienta usar y qué A2UI pintar.</p>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="Reiniciar chat" onClick={() => clearMutation.mutate()}>
          <RotateCcw className="size-4" aria-hidden="true" />
        </Button>
      </div>

      <div className="flex-1 space-y-3">
        {messagesQuery.isPending ? <ConversationSkeleton /> : null}
        {messagesQuery.data ? (
          <A2UIRenderer blocks={messagesQuery.data.blocks} onChipClick={sendText} />
        ) : null}
        {isSending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Pensando...
          </div>
        ) : null}
        {error ? <InlineError message={error} /> : null}
      </div>

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          sendText(draft)
        }}
      >
        <Textarea
          aria-label="Mensaje para Kalmio"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Añade origen, destino, hotel, batería o preferencias..."
          className="min-h-20 border-0 px-2 shadow-none focus-visible:outline-none"
        />
        <div className="flex items-center justify-end pt-2">
          <Button type="submit" size="sm" disabled={isSending || draft.trim().length === 0}>
            <ArrowUp className="size-4" aria-hidden="true" />
            Enviar
          </Button>
        </div>
      </form>
    </section>
  )
}

function ActivityPage() {
  const authQuery = useQuery({ queryKey: authQueryKey, queryFn: getCurrentUser })
  const plansQuery = useQuery({
    queryKey: routePlansQueryKey,
    queryFn: listRoutePlans,
    enabled: authQuery.data?.authenticated === true,
  })

  return (
    <section className="space-y-4">
      <PageHeading title="Planes" text="Historial guardado de planes EV completos para tu cuenta." />
      {authQuery.isPending || (authQuery.data?.authenticated && plansQuery.isPending) ? <ConversationSkeleton /> : null}
      {!authQuery.isPending && !authQuery.data?.authenticated ? (
        <AccountRequiredCard text="Inicia sesión para consultar planes guardados. La conversación anónima vive solo en la sesión actual." />
      ) : null}
      {plansQuery.error ? <InlineError message={plansQuery.error instanceof Error ? plansQuery.error.message : 'No se pudo cargar el historial.'} /> : null}
      {plansQuery.data && plansQuery.data.length > 0 ? <RoutePlanHistory plans={plansQuery.data} /> : null}
      {plansQuery.data && plansQuery.data.length === 0 ? (
        <Card>
          <CardContent className="flex items-start gap-3 p-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-md bg-muted text-foreground">
              <ClipboardList className="size-5" aria-hidden="true" />
            </span>
            <div className="space-y-1">
              <h2 className="font-bold">Todavía no hay planes guardados</h2>
              <p className="text-sm leading-6 text-muted-foreground">
                El agente puede explorar cargadores sin cuenta. El guardado queda reservado para planes EV completos.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </section>
  )
}

function SettingsPage() {
  return (
    <section className="space-y-4">
      <PageHeading title="Cuenta" text="Sesión para consultar tus planes guardados cuando existan." />
      <AccountPanel />
    </section>
  )
}

function RoutePlanHistory({ plans }: { plans: RoutePlanResponse[] }) {
  return (
    <div className="space-y-3">
      {plans.map((plan) => (
        <Card key={plan.id ?? `${plan.origin_label}-${plan.destination_label}-${plan.created_at}`}>
          <CardContent className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">
                  {plan.origin_label} {'->'} {plan.destination_label}
                </h2>
                <p className="text-xs leading-5 text-muted-foreground">
                  {plan.created_at ? new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(plan.created_at)) : 'Sin fecha'}
                </p>
              </div>
              <span className="rounded-full bg-muted px-2 py-1 text-xs font-medium text-foreground">
                {plan.arrival_battery_percent !== null ? `${plan.arrival_battery_percent}%` : 'Exploración'}
              </span>
            </div>
            <MetricRows
              rows={[
                ['Cargador', plan.recommendation.name],
                ['Ruta', `${plan.distance_km} km · ${plan.duration_min} min`],
                ['Energía', plan.energy_kwh !== null ? `${plan.energy_kwh} kWh` : 'No calculada'],
              ]}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function AccountPanel() {
  const authQuery = useQuery({ queryKey: authQueryKey, queryFn: getCurrentUser })
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [form, setForm] = useState<AuthCredentials>(defaultAuthForm)
  const [error, setError] = useState<string | null>(null)
  const submitMutation = useMutation({
    mutationFn: () => (mode === 'login' ? login(form) : register(form)),
    onMutate: () => setError(null),
    onSuccess: (user) => {
      queryClient.setQueryData(authQueryKey, user)
      queryClient.invalidateQueries({ queryKey: routePlansQueryKey })
      setForm(defaultAuthForm)
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : 'No se pudo completar la autenticación.')
    },
  })
  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: (user) => {
      queryClient.setQueryData(authQueryKey, user)
      queryClient.removeQueries({ queryKey: routePlansQueryKey })
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : 'No se pudo cerrar sesión.')
    },
  })

  if (authQuery.isPending) {
    return <ConversationSkeleton />
  }

  if (authQuery.data?.authenticated) {
    return (
      <Card className="bg-muted">
        <CardContent className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-foreground">Sesión activa</p>
              <p className="text-sm leading-6 text-foreground">{authQuery.data.email}</p>
            </div>
            <Button type="button" variant="secondary" size="sm" onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending}>
              Cerrar sesión
            </Button>
          </div>
          {error ? <InlineError message={error} /> : null}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="grid grid-cols-2 gap-2 rounded-md bg-muted p-1">
          <Button type="button" variant={mode === 'login' ? 'default' : 'ghost'} onClick={() => setMode('login')}>
            Entrar
          </Button>
          <Button type="button" variant={mode === 'register' ? 'default' : 'ghost'} onClick={() => setMode('register')}>
            Crear cuenta
          </Button>
        </div>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            submitMutation.mutate()
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="account-email">Email</Label>
            <Input
              id="account-email"
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="account-password">Contraseña</Label>
            <Input
              id="account-password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            />
          </div>
          {error ? <InlineError message={error} /> : null}
          <Button type="submit" className="w-full" disabled={submitMutation.isPending}>
            {submitMutation.isPending ? 'Procesando...' : mode === 'login' ? 'Entrar' : 'Crear cuenta'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function AccountRequiredCard({ text }: { text: string }) {
  return (
    <Card className="bg-muted">
      <CardContent className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-md bg-surface text-foreground">
          <UserRound className="size-5" aria-hidden="true" />
        </span>
        <div className="space-y-2">
          <h2 className="font-semibold text-foreground">Cuenta requerida</h2>
          <p className="text-sm leading-6 text-foreground">{text}</p>
          <Link className="text-sm font-semibold text-link underline-offset-4 hover:underline" to="/settings">
            Ir a Cuenta
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm leading-6">
      <AlertTriangle className="mt-1 size-4 shrink-0 text-foreground" aria-hidden="true" />
      <span>{message}</span>
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

function MetricRows({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid gap-2 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-3">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
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

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/activity',
  component: ActivityPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  chatRoute,
  activityRoute,
  settingsRoute,
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
