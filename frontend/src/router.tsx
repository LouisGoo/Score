import type { ComponentType } from 'react'
import { Navigate, type RouteObject } from 'react-router'
import { NotFound, RouteError } from './components/RouteError'

type Module = Record<string, unknown>

/** 从懒加载分包取出指定组件；同一模块的页面共用一个分包。 */
function page<M extends Module>(load: () => Promise<M>, name: keyof M & string) {
  return async () => ({ Component: (await load())[name] as ComponentType })
}

// 首页也懒加载，使直接打开 /join 的手机只下载入口与评委分包。
const home = () => import('./pages/Home')
const admin = () => import('./admin')
const judge = () => import('./judge')
const screen = () => import('./screen')

export const routes: RouteObject[] = [
  {
    path: '/',
    errorElement: <RouteError />,
    children: [
      { index: true, lazy: page(home, 'Home') },
      {
        path: 'admin',
        lazy: page(admin, 'AdminLayout'),
        children: [
          { index: true, element: <Navigate to="events" replace /> },
          { path: 'login', lazy: page(admin, 'LoginPage') },
          { path: 'events', lazy: page(admin, 'EventListPage') },
          { path: 'events/new', lazy: page(admin, 'EventCreatePage') },
          { path: 'events/:eventId/settings', lazy: page(admin, 'EventSettingsPage') },
          { path: 'events/:eventId/control', lazy: page(admin, 'EventControlPage') },
          { path: 'events/:eventId/results', lazy: page(admin, 'EventResultsPage') },
        ],
      },
      {
        lazy: page(judge, 'JudgeLayout'),
        children: [
          { path: 'join', lazy: page(judge, 'JoinPage') },
          { path: 'join/:publicCode', lazy: page(judge, 'JoinPage') },
          { path: 'judge/events/:eventId', lazy: page(judge, 'JudgeEventPage') },
          { path: 'judge/events/:eventId/history', lazy: page(judge, 'JudgeHistoryPage') },
        ],
      },
      { path: 'screen/:grantId', lazy: page(screen, 'ScreenPage') },
      { path: '*', element: <NotFound /> },
    ],
  },
]
