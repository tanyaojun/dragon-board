import express from 'express'
import swaggerUiDist from 'swagger-ui-dist'

import { buildOpenApiDocument } from '../openapi.js'

const swaggerAssetsPath = swaggerUiDist.getAbsoluteFSPath()

function renderDocsHtml() {
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Dragon Board Proxy API</title>
    <link rel="stylesheet" href="/docs-assets/swagger-ui.css">
    <link rel="icon" href="/docs-assets/favicon-32x32.png">
    <style>
      body { margin: 0; background: #fff; }
      .swagger-ui .topbar { display: none; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="/docs-assets/swagger-ui-bundle.js"></script>
    <script src="/docs-assets/swagger-ui-standalone-preset.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: '/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        layout: 'BaseLayout'
      })
    </script>
  </body>
</html>`
}

export function registerDocsRoutes(app, { port }) {
  app.get('/openapi.json', (req, res) => {
    res.json(buildOpenApiDocument({ port }))
  })

  app.get('/docs', (req, res) => {
    res.type('html').send(renderDocsHtml())
  })

  app.use('/docs-assets', express.static(swaggerAssetsPath, { maxAge: '1d' }))
}

