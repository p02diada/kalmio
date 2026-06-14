import { QueryClient, QueryClientProvider, useMutation, useQuery } from '@tanstack/react-query'
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
} from '@tanstack/react-router'
import {
  Activity,
  AlertTriangle,
  ArrowUp,
  BatteryCharging,
  ClipboardList,
  Home,
  Loader2,
  MessageCircle,
  Navigation,
  RotateCcw,
  Settings,
  Sparkles,
  UserRound,
  Zap,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { A2UIRenderer } from '@/components/a2ui/a2ui-renderer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
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

const queryClient = new QueryClient()
const routePlansQueryKey = ['route-plans'] as const
const pendingPromptKey = 'kalmio.pendingPrompt'

const defaultAuthForm: AuthCredentials = {
  email: '',
  password: '',
}

const quickPrompts = [
  {
    label: 'Cargar cerca de un hotel',
    value: 'Quiero ver cargadores cerca de un hotel en Valencia.',
    icon: BatteryCharging,
  },
  {
    label: 'Preparar ruta',
    value: 'Voy desde Córdoba hasta Valencia con 58%, batería útil 64 kWh, consumo 17.8 kWh/100km, CCS2 y potencia 150 kW.',
    icon: Navigation,
  },
  {
    label: 'Necesito cargar ya',
    value: 'Necesito cargar ya cerca de mi ubicación.',
    icon: Zap,
  },
]

function AppShell() {
  return (
    <div className="min-h-svh bg-background px-0 text-foreground md:bg-muted md:px-6 md:py-8">
      <div className="mx-auto flex min-h-svh w-full max-w-[430px] flex-col bg-surface shadow-none md:min-h-[880px] md:overflow-hidden md:rounded-xl md:border md:border-border md:shadow-[0_12px_32px_oklch(20.5%_0_0_/_0.12)]">
        <header className="sticky top-0 z-10 border-b border-border bg-surface px-6 pb-3 pt-5">
          <div className="flex items-center justify-between gap-3">
            <Link to="/" className="flex items-baseline gap-1" aria-label="Kalmio home">
              <span className="text-[1.05rem] font-semibold leading-none text-primary">Kalmio</span>
              <span className="text-[1.05rem] font-semibold leading-none text-primary">EV</span>
            </Link>
            <span className="grid size-8 place-items-center rounded-full border border-border bg-surface text-foreground shadow-[0_2px_6px_oklch(20.5%_0_0_/_0.08)]">
              <UserRound className="size-4" aria-hidden="true" />
            </span>
          </div>
        </header>

        <main className="flex-1 px-6 pb-24 pt-5">
          <Outlet />
        </main>

        <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface px-3 py-2 md:sticky md:bottom-auto">
          <div className="mx-auto grid max-w-[430px] grid-cols-4 gap-1">
            <NavItem to="/" icon={Home} label="Inicio" />
            <NavItem to="/chat" icon={MessageCircle} label="Chat" />
            <NavItem to="/activity" icon={Activity} label="Planes" />
            <NavItem to="/settings" icon={Settings} label="Cuenta" />
          </div>
        </nav>
      </div>
      <Toaster richColors position="top-center" />
    </div>
  )
}

function NavItem({
  to,
  icon: Icon,
  label,
}: {
  to: string
  icon: typeof Home
  label: string
}) {
  return (
    <Link
      to={to}
      className="flex min-h-12 flex-col items-center justify-center gap-1 rounded-md px-1 text-[0.72rem] font-medium text-muted-foreground transition-colors hover:text-foreground [&.active]:font-semibold [&.active]:text-primary"
    >
      <Icon className="size-4" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  )
}

function HomePage() {
  const navigate = useNavigate()
  const [intent, setIntent] = useState('')

  const startChat = (value: string) => {
    const text = value.trim()
    if (text) {
      sessionStorage.setItem(pendingPromptKey, text)
    }
    navigate({ to: '/chat' })
  }

  return (
    <section className="space-y-5">
      <div className="space-y-2 pt-2">
        <p className="text-[0.82rem] font-semibold uppercase tracking-[0.08em] text-primary">Viaja sin ansiedad de carga</p>
        <h1 className="text-[1.82rem] font-semibold leading-[1.04] text-foreground">¿Qué necesitas hacer ahora?</h1>
        <p className="text-sm leading-6 text-muted-foreground">
          Dime la intención. El agente decidirá si necesita aclarar datos, buscar cargadores o calcular una ruta.
        </p>
      </div>

      <form
        className="rounded-[22px] border border-border bg-surface shadow-[0_6px_14px_oklch(20.5%_0_0_/_0.10)]"
        onSubmit={(event) => {
          event.preventDefault()
          startChat(intent)
        }}
      >
        <div className="flex min-h-14 items-center gap-2 px-4 py-2">
          <Input
            aria-label="Describe lo que necesitas"
            value={intent}
            onChange={(event) => setIntent(event.target.value)}
            placeholder="Ruta, hotel, carga urgente..."
            className="h-10 flex-1 rounded-none border-0 bg-transparent px-0 py-0 text-[0.95rem] shadow-none focus-visible:outline-none"
          />
          <Button type="submit" size="icon" aria-label="Abrir chat" className="size-11 shrink-0 rounded-full">
            <ArrowUp className="size-5" aria-hidden="true" />
          </Button>
        </div>
      </form>

      <div className="space-y-2.5">
        <p className="text-[0.82rem] font-semibold leading-5 text-foreground">Inicio rápido</p>
        <div className="flex flex-col items-start gap-2">
          {quickPrompts.map((prompt) => {
            const Icon = prompt.icon
            return (
              <Button
                key={prompt.label}
                type="button"
                variant="outline"
                size="sm"
                className="h-9 justify-start gap-3 rounded-md border-border bg-surface px-4 text-[0.86rem] font-medium shadow-[0_2px_6px_oklch(20.5%_0_0_/_0.08)] hover:bg-muted"
                onClick={() => startChat(prompt.value)}
              >
                <Icon className="size-4 text-primary" aria-hidden="true" />
                {prompt.label}
              </Button>
            )
          })}
        </div>
      </div>

      <Card className="border-primary/20 bg-primary-soft">
        <CardContent className="flex items-start gap-3 p-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-surface text-primary">
            <Sparkles className="size-5" aria-hidden="true" />
          </span>
          <div className="space-y-1">
            <h2 className="font-bold text-primary">Chat primero, mapa después.</h2>
            <p className="text-sm leading-6 text-foreground">
              Las respuestas se pintan con componentes A2UI permitidos. Si falta una fuente fiable, Kalmio lo dirá.
            </p>
          </div>
        </CardContent>
      </Card>
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

  const sendText = (value: string) => {
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
  }

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
    sendText(pending)
  }, [])

  return (
    <section className="flex min-h-[calc(100svh-9rem)] flex-col gap-4">
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
        className="sticky bottom-[4.8rem] rounded-lg border border-border bg-surface p-2 shadow-[0_8px_20px_oklch(20.5%_0_0_/_0.12)] md:bottom-3"
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
            <span className="grid size-9 shrink-0 place-items-center rounded-md bg-primary-soft text-primary">
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
              <span className="rounded-md bg-primary-soft px-2 py-1 text-xs font-medium text-primary">
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
      <Card className="border-primary/25 bg-primary-soft">
        <CardContent className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-primary">Sesión activa</p>
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
    <Card className="border-primary/25 bg-primary-soft">
      <CardContent className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-md bg-surface text-primary">
          <UserRound className="size-5" aria-hidden="true" />
        </span>
        <div className="space-y-2">
          <h2 className="font-bold text-primary">Cuenta requerida</h2>
          <p className="text-sm leading-6 text-foreground">{text}</p>
          <Link className="text-sm font-semibold text-primary underline-offset-4 hover:underline" to="/settings">
            Ir a Cuenta
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm leading-6">
      <AlertTriangle className="mt-1 size-4 shrink-0 text-warning" aria-hidden="true" />
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
