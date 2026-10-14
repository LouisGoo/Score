import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Navigate, useNavigate, useSearchParams } from 'react-router'
import { adminAuth } from '../api/admin'
import { describeError } from '../api/errors'
import { queryKeys } from '../api/query'
import { clearAdminData, ErrorText, safeNext, useSessionQuery } from './session'

interface LoginValues {
  login: string
  password: string
}

/** 账号规则与后端一致：去空白后 3～64 位，字母数字及 . _ -，首位字母或数字；大小写不敏感。 */
const LOGIN_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$/

export function LoginPage() {
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<LoginValues>()
  const [failure, setFailure] = useState<unknown>(null)

  // 已登录（如刷新登录页或从书签进入）则直接进入；未登录的 401 属于正常状态。
  const current = useSessionQuery({ retry: false })

  const login = useMutation({
    mutationFn: (values: LoginValues) => adminAuth.login(values.login.trim(), values.password),
    onSuccess: session => {
      // 重新登录可能切换账号，丢弃上一身份的全部缓存。
      clearAdminData(queryClient)
      queryClient.setQueryData(queryKeys.adminSession, session)
      navigate(next, { replace: true })
    },
    onError: error => {
      setFailure(error)
      form.setFieldValue('password', '')
    },
  })

  if (current.data) return <Navigate to={next} replace />

  const info = failure ? describeError(failure) : null
  return (
    <div className="login-page">
      <Card className="login-card">
        <Typography.Title level={3}>主办方登录</Typography.Title>
        <Typography.Paragraph type="secondary">账号由系统管理员在服务端创建。</Typography.Paragraph>
        {info && (
          <Alert
            className="form-alert"
            type={info.action === 'wait' ? 'warning' : 'error'}
            showIcon
            title={info.code === 'INVALID_CREDENTIALS' ? '账号或密码不正确' : '登录失败'}
            description={info.code === 'INVALID_CREDENTIALS' ? undefined : <ErrorText info={info} />}
          />
        )}
        <Form<LoginValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          disabled={login.isPending}
          onFinish={values => {
            setFailure(null)
            login.mutate(values)
          }}
        >
          <Form.Item
            label="账号"
            name="login"
            rules={[
              { required: true, whitespace: true, message: '请输入账号' },
              {
                validator: (_, value?: string) =>
                  !value?.trim() || LOGIN_PATTERN.test(value.trim())
                    ? Promise.resolve()
                    : Promise.reject(new Error('账号为 3～64 位字母、数字、点、下划线或连字符')),
              },
            ]}
          >
            <Input autoComplete="username" autoFocus maxLength={64} />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }, { max: 128, message: '密码最多 128 位' }]}>
            <Input.Password autoComplete="current-password" maxLength={128} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={login.isPending}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
