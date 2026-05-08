import { describe, expect, it } from 'vitest'

import { refreshCoordinator } from '../RefreshCoordinator'

describe('RefreshCoordinator service registry', () => {
  it('does not run a second dataLoader merge after runUpdate', () => {
    const registry = (refreshCoordinator as any).SERVICE_REGISTRY as Array<{
      name: string
      fullMethod?: string
      syncMethod?: string
    }>

    expect(registry.find((service) => service.name === 'dataLoader')).toEqual(
      expect.objectContaining({
        fullMethod: 'runUpdate',
      }),
    )
    expect(registry.find((service) => service.name === 'dataLoader')).not.toHaveProperty(
      'syncMethod',
    )
  })
})
