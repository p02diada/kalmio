import { KalmioBrandMark } from '@/components/brand/kalmio-brand-mark'
import { chatWaitingMessages } from '@/components/chat/chat-waiting-messages'

export function ChatPendingStatus({ messageIndex, message: progressMessage }: { messageIndex: number; message?: string }) {
  const safeMessageIndex = Math.min(messageIndex, chatWaitingMessages.length - 1)
  const message = progressMessage || chatWaitingMessages[safeMessageIndex]

  return (
    <div className="chat-pending-status" role="status" aria-live="polite" aria-atomic="true">
      <span className="chat-pending-status-mark" aria-hidden="true">
        <KalmioBrandMark className="size-4" />
      </span>
      <span className="chat-pending-status-copy">
        <span key={message} className="chat-pending-status-message">{message}</span>
      </span>
      <span className="chat-pending-status-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  )
}
