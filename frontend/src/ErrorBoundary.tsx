import { Component, type ErrorInfo, type JSX, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  failed: boolean
}

/** Catches a crash anywhere below it and shows a friendly screen instead of a blank page.
 * The error itself goes to the console only, never on screen. A class, because React has
 * no hook for this. Plain <a>, not a router Link: the router may be what crashed. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Something went wrong', error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return <CrashScreen />
  }
}

function CrashScreen(): JSX.Element {
  const home = window.location.pathname.startsWith('/staff') ? '/staff' : '/'
  return (
    <main className="page" role="alert">
      <h1>Something went wrong</h1>
      <p>Sorry, something went wrong on our side. Please try again.</p>
      <p className="not-found-links">
        <button
          type="button"
          onClick={() => {
            window.location.reload()
          }}
        >
          Reload
        </button>
        <a href={home}>Go to home page</a>
      </p>
    </main>
  )
}
