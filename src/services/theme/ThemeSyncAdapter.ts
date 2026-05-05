import { themeFacade } from './ThemeFacade'

export const themeSyncAdapter = {
  async runUpdate() {
    return themeFacade.refreshRuntime({
      source: 'themeRuntime',
      forceJxbk: true,
      syncStocks: true,
    })
  },

  async syncData() {
    return themeFacade.refreshRuntime({
      source: 'themeRuntime',
      syncStocks: true,
    })
  },

  async syncThemesToStocks() {
    return this.syncData()
  },
}

export default themeSyncAdapter
