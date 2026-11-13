# 构建与部署

以下命令在包含 `package.json` 的项目目录执行。本模板仓库的项目目录为 `next-shadcn-dashboard-starter/`；部署平台也应将它设置为构建根目录。

## 在服务器运行

```bash
bun install --frozen-lockfile
bun run build
bun run start
```

应用默认监听 3000 端口。按部署环境配置域名、HTTPS 和反向代理；AI Chat 使用 SSE，代理需要关闭该接口的响应缓冲，并允许长连接。

## 部署到 Vercel

1. 导入由模板创建的项目仓库。
2. 如果保留本仓库目录结构，将 Root Directory 设为 `next-shadcn-dashboard-starter`。
3. 使用 `bun install --frozen-lockfile` 安装，使用 `bun run build` 构建。
4. 在平台配置项目需要的环境变量后部署。

## Docker

项目提供 Node.js 运行时的 `Dockerfile` 和 Bun 运行时的 `Dockerfile.bun`。两者在构建阶段设置 `BUILD_STANDALONE=true`，生成并使用 Next.js standalone 产物。

```bash
# Node.js 运行时
docker build -t shadcn-dashboard .

# 或 Bun 运行时
docker build -f Dockerfile.bun -t shadcn-dashboard .

# 启动所选镜像
docker run -d -p 3000:3000 --restart unless-stopped --name shadcn-dashboard shadcn-dashboard
```

如需自定义构建时环境变量，在 Dockerfile 中显式声明对应 `ARG` / `ENV` 后传入；运行时变量使用 `docker run -e` 或平台配置。

## Standalone 模式

`next.config.ts` 仅在 `BUILD_STANDALONE` 等于字符串 `true` 时启用 standalone；普通 `bun run build` 不会自动开启。手动自托管 standalone 时，构建前设置该变量，并一并部署 `.next/standalone`、`.next/static` 和 `public`。

## 环境变量

以 `env.example.txt` 为配置入口，只设置所选功能需要的变量：

- `NEXT_PUBLIC_*` 会进入浏览器构建产物，变更后需要重新构建，不应包含服务端密钥。
- `BUILD_STANDALONE=true` 用于 standalone 构建，Dockerfile 已设置。
- 使用 Sentry 时配置 `NEXT_PUBLIC_SENTRY_DSN`、组织、项目和服务端 `SENTRY_AUTH_TOKEN`；不启用时可设置 `NEXT_PUBLIC_SENTRY_DISABLED=true`。
- Sentry sourcemap 上传需要相应组织、项目及授权配置，不能仅凭执行构建就认为已上传。

模板中的 API 默认使用演示数据。部署业务项目时，通过各功能的数据层接入实际服务，配置项目自己的鉴权、密钥和文件存储。

AI 接口说明见 [AI Chat 开发指南](./aichat/README.md)。
