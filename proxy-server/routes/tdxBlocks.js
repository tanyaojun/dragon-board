import { sendBadRequest } from '../helpers/response.js'
import { loadTdxBlockCodes, saveTdxBlockSelection, scanTdxBlockFiles } from '../services/tdxBlocks.js'

function buildErrorDetails(error) {
  return {
    code: error?.code,
    path: error?.path,
  }
}

export function registerTdxBlockRoutes(app, { readConfig }) {
  app.get('/api/tdx-blocks', async (req, res) => {
    try {
      const data = await scanTdxBlockFiles({ readConfig })
      res.json({ ok: true, source: 'tdx-blocks', data })
    } catch (error) {
      sendBadRequest(
        res,
        'tdx_block_dir_unavailable',
        error instanceof Error ? error.message : String(error),
        buildErrorDetails(error),
      )
    }
  })

  app.get('/api/tdx-blocks/codes', async (req, res) => {
    try {
      const data = await loadTdxBlockCodes({ readConfig, files: req.query.files })
      res.json({ ok: true, source: 'tdx-blocks', data })
    } catch (error) {
      sendBadRequest(
        res,
        'tdx_block_codes_unavailable',
        error instanceof Error ? error.message : String(error),
        buildErrorDetails(error),
      )
    }
  })

  app.post('/api/tdx-blocks/selection', async (req, res) => {
    try {
      const data = await saveTdxBlockSelection({ readConfig, files: req.body?.files })
      res.json({ ok: true, source: 'tdx-blocks', data })
    } catch (error) {
      sendBadRequest(
        res,
        'tdx_block_selection_unavailable',
        error instanceof Error ? error.message : String(error),
        buildErrorDetails(error),
      )
    }
  })
}
