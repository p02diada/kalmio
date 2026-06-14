import '@testing-library/jest-dom/vitest'

Object.defineProperty(window, 'scrollTo', {
  value: () => undefined,
  writable: true,
})

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, 'ResizeObserver', {
  value: ResizeObserverMock,
  writable: true,
})
