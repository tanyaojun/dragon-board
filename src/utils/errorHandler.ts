// src/utils/errorHandler.ts

export class ErrorHandler {
  /**
   * 同步执行并捕获错误
   */
  static trySync<T>(fn: () => T, context: string, defaultValue: T): T {
    try {
      return fn()
    } catch (error) {
      this.log(error, context)
      return defaultValue
    }
  }

  /**
   * 异步执行并捕获错误
   */
  static async tryAsync<T>(
    promise: Promise<T>,
    context: string,
    defaultValue: T
  ): Promise<T> {
    try {
      return await promise
    } catch (error) {
      this.log(error, context)
      return defaultValue
    }
  }

  /**
   * 处理错误（不返回值）
   */
  static handle(error: unknown, context: string): void {
    this.log(error, context)
    
    // 生产环境可以上报
    if (import.meta.env.PROD) {
      // 这里可以添加错误上报逻辑
      // reportError(error, context)
    }
  }

  /**
   * 记录错误
   */
  private static log(error: unknown, context: string): void {
    const timestamp = new Date().toISOString()
    const message = error instanceof Error ? error.message : String(error)
    const stack = error instanceof Error ? error.stack : ''
    
    console.error(`[ErrorHandler] ${timestamp} ${context}:`, {
      message,
      stack,
      error
    })
  }

  /**
   * 创建错误边界
   */
  static createBoundary<T>(fn: () => T, context: string, fallback: T): () => T {
    return () => this.trySync(fn, context, fallback)
  }
}

// 全局挂载（可选，为了兼容旧代码）
if (typeof window !== 'undefined') {
  ;(window as any).ErrorHandler = ErrorHandler
}