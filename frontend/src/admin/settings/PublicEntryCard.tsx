import { Card, Descriptions, Flex, QRCode, Typography } from 'antd'
import type { EventInfo } from '../../api/types'
import { formatTime, publicJoinUrl } from '../format'

/** 公共入口：只含活动码，可公开张贴或投屏；个人身份码需另行私下分发。 */
export function PublicEntryCard({ event }: { event: EventInfo }) {
  if (!event.public_code) return null
  const url = publicJoinUrl(event.public_code)
  return (
    <Card title="评委入口" size="small">
      <Flex gap={24} wrap align="center">
        <QRCode value={url} size={148} />
        <Descriptions
          column={1}
          size="small"
          items={[
            {
              key: 'code',
              label: '活动码',
              children: <Typography.Text copyable strong className="credential-code">{event.public_code}</Typography.Text>,
            },
            { key: 'url', label: '加入链接', children: <Typography.Text copyable>{url}</Typography.Text> },
            { key: 'published', label: '发布时间', children: formatTime(event.published_at) },
          ]}
        />
      </Flex>
      <Typography.Paragraph type="secondary" className="entry-note">
        评委扫码或访问链接后输入个人身份码；活动码本身不能用于评分。
      </Typography.Paragraph>
    </Card>
  )
}
