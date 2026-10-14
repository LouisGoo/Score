import type { ThemeConfig } from 'antd'

export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#256044',
    colorLink: '#256044',
    colorText: '#172e29',
    colorBgLayout: '#f5f4ef',
    borderRadius: 6,
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
    // 手机评分的触控区域不小于 44px。
    controlHeightLG: 44,
  },
}
