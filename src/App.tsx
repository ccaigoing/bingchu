// 全局样式只在这里引一次。顺序与层叠说明见 styles/globals.css 顶部。
import '@styles/globals.css'

import { Providers } from './app/providers'

export default function App() {
  return <Providers />
}
