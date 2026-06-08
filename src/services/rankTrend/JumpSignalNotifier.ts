import type { JumpSignalResult } from './jumpSignalService'

/**
 * 旧 jump 飞书/候选池链路已下线。
 * 保留兼容壳，避免旧 import 在运行时直接报错。
 */
export class JumpSignalNotifier {
  async notifyEntry(_stock: Record<string, any>, _result: JumpSignalResult): Promise<void> {}

  async notifyExit(_stock: Record<string, any>, _result: JumpSignalResult): Promise<void> {}
}

export const jumpSignalNotifier = new JumpSignalNotifier()
