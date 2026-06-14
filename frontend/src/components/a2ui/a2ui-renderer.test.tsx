import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { A2UIRenderer } from './a2ui-renderer'

describe('A2UIRenderer', () => {
  it('renders a fallback for unknown blocks', () => {
    render(<A2UIRenderer blocks={[{ id: 'x', type: 'UnknownCard', version: 1, props: {} }]} />)

    expect(screen.getByText('Bloque no disponible')).toBeInTheDocument()
    expect(screen.getByText('UnknownCard')).toBeInTheDocument()
  })

  it('explains disabled actions', () => {
    render(
      <A2UIRenderer
        blocks={[
          {
            id: 'actions',
            type: 'ActionButtons',
            version: 1,
            props: {
              actions: [
                {
                  label: 'Abrir en Maps',
                  disabled: true,
                  reason: 'Faltan coordenadas u origen confirmado.',
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Abrir en Maps' })).toBeDisabled()
    expect(screen.getByText('Faltan coordenadas u origen confirmado.')).toBeInTheDocument()
  })
})
