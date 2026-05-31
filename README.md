# BUPT 空教室日程助手

基于 Python/FastAPI 与 React/Vite 的北邮空教室查询工具。项目参考了：

- `Nemoyuzx/BUPT-Auto-Syllabu--` 的新版教务课表登录与 XLS 解析流程
- `Jraaay/EmptyClassroom` 的微信教务空教室接口与按节次聚合思路

## 功能

- 查看指定校区当天空教室。
- 获取个人课表，并按指定日期计算个人忙闲节次。
- 用个人空闲节次筛选空教室。
- 推荐可以连续待着、不用换教室的候选教室。

## 本地运行

后端：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。

## 账号配置

前端表单可以直接输入学号和教务密码。也可以复制 `.env.example` 为 `.env`，在后端环境变量中配置：

```bash
BUPT_USERNAME=你的学号
BUPT_PASSWORD=你的教务密码
```

`.env` 已被 `.gitignore` 忽略，不要提交真实密码。

空教室数据只使用北邮微信教务实时接口；如果登录失败或接口不可用，页面会直接显示错误。

## 默认学期

默认配置为：

- 学期：`2025-2026-2`
- 第一周周一：`2026-03-02`

如果课表周次不对，优先检查前端查询条件中的“第一周周一”。
