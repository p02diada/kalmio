export function StationConnectorBadge({ connector }: { connector: string }) {
  return (
    <span className="max-w-full rounded-full bg-primary px-2 py-1 text-caption font-semibold leading-4 text-primary-foreground [overflow-wrap:anywhere]">
      {connector}
    </span>
  )
}
