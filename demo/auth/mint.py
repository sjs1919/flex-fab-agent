"""本地签发 Token CLI -- demo 调试台 judge/重跑/标注等写端点鉴权用（R-7）。

调试台前端（/portal/debug）的 admin token 输入框需要有效 token：
token 由 STS 签发、存 tokens.db、1 小时有效。测试与 supervisor 内部可自签，
但用户侧此前无签发入口，导致 judge 等写端点 401。此 CLI 补齐该入口。

用法（agent-training 仓库根目录）：
  python -m demo.auth.mint admin          # 签发 admin token（1h 有效，贴进调试台输入框）
  python -m demo.auth.mint scheduler      # 其他角色（reviewer/operator/viewer）
"""
import sys

from .token_exchange import STS, RoleType

ROLES: list[str] = ["admin", "scheduler", "reviewer", "operator", "viewer"]


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else "admin"
    if role not in ROLES:
        print(f"角色 {role} 无效，可选：{', '.join(ROLES)}")
        sys.exit(2)
    token_id = STS().issue_user_token(f"dev-{role}", role)  # type: ignore[arg-type]
    print(token_id)
    print(f"角色：{role} | 有效期：1 小时 | 请求头：X-Admin-Token: {token_id}")


if __name__ == "__main__":
    main()
