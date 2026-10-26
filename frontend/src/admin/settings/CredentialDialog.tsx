import { useState } from 'react'
import { Alert, Button, Flex, Modal, QRCode, Table, Typography } from 'antd'
import type { CredentialResult } from '../../api/types'
import { privateInviteUrl } from '../format'

export interface IssuedCredential {
  result: CredentialResult
  number: string
  name: string
}

interface Props {
  title: string
  items: IssuedCredential[]
  /** 已发布活动的活动码；草稿没有活动码，无法生成私人邀请。 */
  publicCode: string | null
  onClose: () => void
}

/**
 * 身份码按需获取后仅保存在对话框状态中，关闭即丢弃；下次查看重新向服务端请求。
 */
export function CredentialDialog({ title, items, publicCode, onClose }: Props) {
  const [qrFor, setQrFor] = useState<string | null>(items.length === 1 ? items[0].result.judge_id : null)
  const shown = items.find(i => i.result.judge_id === qrFor)

  const allText = items
    .map(i => [i.number, i.name, i.result.code, publicCode ? privateInviteUrl(publicCode, i.result.code) : ''].filter(Boolean).join('\t'))
    .join('\n')

  return (
    <Modal
      open
      title={title}
      width={items.length > 1 ? 820 : 560}
      mask={{ closable: false }}
      keyboard={false}
      onCancel={onClose}
      footer={<Button type="primary" onClick={onClose}>完成</Button>}
    >
      <Alert
        type="warning"
        showIcon
        className="form-alert"
        title="身份码可再次查看"
        description={
          publicCode
            ? '关闭后可在“评委与身份码”中再次查看和复制。请私下分发给对应评委，私人邀请二维码请勿投屏或公开张贴。'
            : '关闭后可在“评委与身份码”中再次查看和复制。活动发布后，再次查看即可获取私人邀请二维码。'
        }
      />
      <Table<IssuedCredential>
        rowKey={i => i.result.judge_id}
        dataSource={items}
        pagination={false}
        size="small"
        scroll={{ y: 360 }}
        columns={[
          { title: '编号', dataIndex: 'number', width: 90 },
          { title: '姓名', dataIndex: 'name' },
          {
            title: '身份码',
            render: (_, i) => <Typography.Text code copyable className="credential-code">{i.result.code}</Typography.Text>,
          },
          ...(publicCode
            ? [
                {
                  title: '私人邀请',
                  width: 120,
                  render: (_: unknown, i: IssuedCredential) => (
                    <Button size="small" type={qrFor === i.result.judge_id ? 'primary' : 'default'} onClick={() => setQrFor(i.result.judge_id)}>
                      二维码
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      {items.length > 1 && (
        <Typography.Paragraph copyable={{ text: allText, tooltips: ['复制全部', '已复制'] }} className="copy-all">
          复制全部（编号、姓名、身份码{publicCode ? '、邀请链接' : ''}）
        </Typography.Paragraph>
      )}
      {publicCode && shown && (
        <Flex gap={16} align="center" className="invite-qr">
          <QRCode value={privateInviteUrl(publicCode, shown.result.code)} size={160} bordered={false} />
          <div>
            <Typography.Text strong>{shown.number} {shown.name} 的私人邀请</Typography.Text>
            <Typography.Paragraph type="secondary">扫码后自动验证身份码，评委仍需确认姓名与编号。</Typography.Paragraph>
            <Typography.Text copyable={{ text: privateInviteUrl(publicCode, shown.result.code) }}>复制邀请链接</Typography.Text>
          </div>
        </Flex>
      )}
    </Modal>
  )
}
