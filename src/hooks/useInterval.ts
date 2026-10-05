import { useEffect, useRef } from 'react'

/**
 * 稳定的 setInterval。与裸 setInterval 的两个区别：
 *
 * 1. **callback 放 ref 里**，不进依赖数组 —— 否则每次渲染产生的新函数
 *    都会重建定时器，计时被无限重置，看起来像"定时器不触发"。
 * 2. **delay 传 null 可暂停** —— 抽成声明式，不用在调用处写 if 分支。
 *
 * 本项目的定位（阶段二 2.5 之后）：业务心跳一律在后端后台协程里，
 * 前端只用它做纯 UI 的事，例如 Topbar 的时钟、以及 useSSE 降级后的轮询。
 * 不要把传感器漂移、预警生成这类有业务含义的节奏搬回前端 ——
 * 那正是这次重构要消灭的东西（见计划书 (d) 节）。
 */
export function useInterval(callback: () => void, delay: number | null): void {
  const saved = useRef(callback)

  useEffect(() => {
    saved.current = callback
  }, [callback])

  useEffect(() => {
    if (delay === null) return
    const id = setInterval(() => saved.current(), delay)
    return () => clearInterval(id)
  }, [delay])
}
