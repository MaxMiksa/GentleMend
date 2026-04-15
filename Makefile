# ============================================================
# 浅愈(GentleMend) — 项目管理 Makefile
# 使用: make help 查看所有可用命令
# ============================================================

.PHONY: help setup dev stop test lint migrate seed clean logs status

# 默认目标
.DEFAULT_GOAL := help

# 颜色定义
CYAN  := \033[36m
GREEN := \033[32m
RESET := \033[0m

help: ## 显示帮助信息
	@echo ""
	@echo "$(CYAN)浅愈(GentleMend) — 可用命令$(RESET)"
	@echo "────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ============================================================
# 环境管理
# ============================================================

setup: ## 首次安装 — 初始化环境变量 + 构建镜像
	@echo "$(CYAN)[1/3] 初始化环境变量...$(RESET)"
	@test -f .env || cp .env.example .env
	@echo "$(CYAN)[2/3] 构建 Docker 镜像...$(RESET)"
	docker compose build
	@echo "$(CYAN)[3/3] 启动基础设施 (等待健康检查)...$(RESET)"
	docker compose up -d postgres redis
	@echo "$(GREEN)Setup 完成! 运行 make dev 启动开发环境$(RESET)"

dev: ## 启动开发环境 (全部服务)
	docker compose up -d
	@echo ""
	@echo "$(GREEN)服务已启动:$(RESET)"
	@echo "  Backend:  http://localhost:$${BACKEND_PORT:-8000}"
	@echo "  Frontend: http://localhost:$${FRONTEND_PORT:-3000}"
	@echo "  API Docs: http://localhost:$${BACKEND_PORT:-8000}/docs"
	@echo "  健康检查: http://localhost:$${BACKEND_PORT:-8000}/api/health"
	@echo ""

stop: ## 停止所有服务
	docker compose down

status: ## 查看服务状态
	docker compose ps

logs: ## 查看服务日志 (实时)
	docker compose logs -f --tail=50

logs-backend: ## 查看后端日志
	docker compose logs -f --tail=100 backend

# ============================================================
# 测试 & 代码质量
# ============================================================

test: ## 运行全部测试
	cd backend && python -m pytest tests/ -v --tb=short --cov=app --cov-report=term-missing

test-unit: ## 运行单元测试
	cd backend && python -m pytest tests/ -v -m "not integration" --tb=short

test-integration: ## 运行集成测试 (需要数据库)
	cd backend && python -m pytest tests/ -v -m integration --tb=short

lint: ## 代码检查 (ruff + mypy)
	cd backend && python -m ruff check app/ tests/
	cd backend && python -m ruff format --check app/ tests/
	cd backend && python -m mypy app/ --ignore-missing-imports

lint-fix: ## 自动修复代码风格
	cd backend && python -m ruff check --fix app/ tests/
	cd backend && python -m ruff format app/ tests/

# ============================================================
# 数据库管理
# ============================================================

migrate: ## 执行数据库迁移
	cd backend && python -m alembic upgrade head

migrate-new: ## 创建新迁移 (用法: make migrate-new MSG="add_xxx_table")
	cd backend && python -m alembic revision --autogenerate -m "$(MSG)"

seed: ## 导入种子数据 (开发/演示用)
	docker compose exec backend python -m app.scripts.seed

# ============================================================
# 清理
# ============================================================

clean: ## 清理容器、数据卷、缓存
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)清理完成$(RESET)"

clean-data: ## 仅清理数据卷 (重置数据库)
	docker compose down -v
	@echo "$(GREEN)数据卷已清理，下次启动将重新初始化数据库$(RESET)"
