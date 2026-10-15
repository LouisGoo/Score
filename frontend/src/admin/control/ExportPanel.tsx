import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Card, Checkbox, Select, Space, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { adminExports, type ExportKind } from '../../api/admin'
import { saveDownload } from '../../lib/download'
import { useReportError } from '../session'

export function ExportPanel({ eventId }: { eventId: string }) {
  const [kind, setKind] = useState<ExportKind>('summary')
  const [includeUnpublished, setIncludeUnpublished] = useState(false)
  const [loading, setLoading] = useState(false)
  const active = useRef<AbortController | null>(null)
  const report = useReportError()
  const { message } = App.useApp()
  useEffect(() => () => active.current?.abort(), [])

  async function download() {
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setLoading(true)
    try {
      const file = await adminExports.download(eventId, kind, includeUnpublished, controller.signal)
      if (controller.signal.aborted) return
      saveDownload(file)
      message.success('文件已交给浏览器下载')
    } catch (error) {
      if (!controller.signal.aborted) report(error, '导出失败')
    } finally {
      active.current = null
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return (
    <Card title="导出成绩与审计" size="small">
      <Space orientation="vertical" size="middle" className="full-width">
        <Space wrap>
          <Select<ExportKind>
            aria-label="导出类型"
            value={kind}
            onChange={setKind}
            disabled={loading}
            style={{ minWidth: 160 }}
            options={[
              { value: 'summary', label: '成绩汇总' },
              { value: 'details', label: '评分明细' },
              { value: 'audit', label: '操作审计' },
            ]}
          />
          <Checkbox checked={includeUnpublished} disabled={loading} onChange={e => setIncludeUnpublished(e.target.checked)}>
            包含未公布
          </Checkbox>
          <Button icon={<DownloadOutlined />} loading={loading} onClick={() => void download()}>
            {loading ? '正在生成并下载' : '下载 CSV'}
          </Button>
        </Space>
        {includeUnpublished && <Alert type="warning" showIcon title="文件将包含未公布数据，仅供内部核对，请谨慎分享。" />}
        <Typography.Text type="secondary">
          默认仅导出已公布任务；操作审计另含活动级记录。文件包含中文表头，可用 Excel 打开。
          导出以下载时的最新数据为准；若与页面不同，请刷新核对。
        </Typography.Text>
      </Space>
    </Card>
  )
}
