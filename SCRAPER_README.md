# ProductHunt Team Member Scraper

独立的Playwright脚本,用于爬取ProductHunt产品页面的team member信息。

## 功能特点

- ✅ 从Feishu Bitable读取待处理记录(team_members字段为空)
- ✅ 使用Playwright点击"Team"按钮
- ✅ 提取team member姓名
- ✅ 直接更新到Feishu Bitable
- ✅ 支持Cookie认证绕过Cloudflare
- ✅ 支持代理配置
- ✅ 完善的错误处理和日志

## 使用方法

### 1. 测试单个URL

```bash
# 激活虚拟环境
source .venv/bin/activate

# 测试单个产品
python scrape_team_members.py --url "https://www.producthunt.com/products/extract-by-firecrawl"
```

### 2. 批量处理(从Feishu读取)

```bash
# 处理所有team_members为空的记录
python scrape_team_members.py

# 限制处理数量
python scrape_team_members.py --limit 10

# 试运行(不更新Feishu,仅输出结果)
python scrape_team_members.py --dry-run
```

### 3. 集成到Workflow

在`.env`文件中添加:

```bash
# 启用team member scraper(可选)
ENABLE_TEAM_SCRAPER=true
```

然后正常运行workflow:

```bash
python wokflow.py --once
```

Workflow会在主同步完成后,自动异步调用team member scraper。

## 配置

需要在`.env`文件中配置以下变量:

```bash
# Feishu配置(必需)
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_TABLE_APP_ID=...
FEISHU_TABLE_ID=...

# ProductHunt Cookies(强烈推荐,用于绕过Cloudflare)
PH_COOKIES=cookie1=value1; cookie2=value2

# 代理(可选)
http_proxy=http://127.0.0.1:7890
https_proxy=http://127.0.0.1:7890
```

### 如何获取ProductHunt Cookies

1. 在浏览器中打开ProductHunt并登录
2. 按F12打开开发者工具
3. 进入Application/Storage标签
4. 展开Cookies → https://www.producthunt.com
5. 复制所有cookies,格式: `key1=value1; key2=value2`
6. 添加到`.env`文件的`PH_COOKIES`变量

**重要的cookies**:
- `_producthunt_session` - 会话cookie
- `cf_clearance` - Cloudflare clearance
- `__cf_bm` - Cloudflare bot management

## 常见问题

### Q: 为什么找不到team members?

A: 可能原因:
1. **Cloudflare验证** - 添加`PH_COOKIES`到`.env`文件
2. **网络问题** - 配置代理或检查网络连接
3. **页面结构变化** - ProductHunt可能更新了页面结构

### Q: 如何查看详细日志?

A: 脚本会输出详细的DEBUG日志,包括:
- 访问的URL
- 找到的Team按钮
- 提取的team member数量
- 匹配的选择器

### Q: 为什么比workflow慢?

A: team member scraper需要:
1. 启动Playwright浏览器
2. 加载完整页面
3. 点击按钮并等待
4. 提取数据

这比API调用慢,但能获取API不提供的数据。

## 性能建议

1. **分批处理**: 使用`--limit`参数限制每次处理数量
2. **定时运行**: 在低峰时段运行,不影响主workflow
3. **手动触发**: 只在需要时运行,而不是每次都运行

## 技术细节

### 选择器策略

脚本使用多个备选选择器来查找team members:

1. `a[href^="/@"].text-16.font-semibold` - 最精确
2. `a[href^="/@"].font-semibold` - 较宽松
3. `a[href^="/@"]` - 所有用户链接

### Cloudflare绕过

通过添加cookies到Playwright context:
- 模拟已认证的浏览器会话
- 避免触发Cloudflare验证
- 提高成功率
