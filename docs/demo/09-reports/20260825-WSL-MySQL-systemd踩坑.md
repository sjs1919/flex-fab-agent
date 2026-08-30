# WSL 部署 MySQL 踩坑：systemd 兼容性 + mysqld_safe 启动

> **日期**：2026-08-25
> **环境**：WSL2 + Ubuntu 26.04 LTS + MySQL 8.4
> **结论**：WSL2 下建议关 systemd，用 `mysqld_safe` 手动启动 MySQL，比 systemd 稳定得多。

---

## 坑 1：WSL2 + Ubuntu 26.04 默认启用 systemd，MySQL 启动后很快挂掉

### 现象
- `sudo service mysql start` 显示 active (running)
- 几秒后再查就不行了，`Can't connect to local MySQL server through socket`
- 错误日志里可能看到 `Received SHUTDOWN from user <via user signal>`

### 根因
Ubuntu 26.04 默认启用 systemd（`/etc/wsl.conf` 里 `systemd=true`），但 WSL2 的 systemd 支持有兼容性问题，特别是 MySQL 这种需要持续运行的守护进程，容易被 systemd 误杀或者 user session 崩溃导致连带挂掉。

### 解决
在 `/etc/wsl.conf` 里关闭 systemd：

```ini
[boot]
systemd=false

[automount]
options = "metadata"
```

然后 `wsl --shutdown` 重启 WSL。

---

## 坑 2：关了 systemd 后，`service mysql start` 报 "unrecognized service"

### 现象
```
$ sudo service mysql start
mysql: unrecognized service
```

### 根因
MySQL 8.4 的 deb 包是纯 systemd 的，不带 init.d 脚本（`/etc/init.d/mysql` 不存在）。关了 systemd 后 `service` 命令找不到脚本。

### 解决
直接用 `mysqld_safe` 启动，先创建运行目录：

```bash
# 创建 socket 目录（每次 WSL 重启后 /var/run 会清空，需要重新建）
sudo mkdir -p /var/run/mysqld
sudo chown mysql:mysql /var/run/mysqld
sudo chmod 755 /var/run/mysqld

# 后台启动 MySQL
sudo mysqld_safe --datadir=/var/lib/mysql --pid-file=/var/run/mysqld/mysqld.pid &

# 等待就绪（约 7-15 秒）
sleep 10

# 验证
sudo mysqladmin ping
```

---

## 坑 3：`sudo mysql` 默认走 socket，但 socket 文件不存在

### 现象
```
ERROR 2002 (HY000): Can't connect to local MySQL server through socket '/var/run/mysqld/mysqld.sock' (2)
```

### 根因
`/var/run/mysqld/` 目录不存在，MySQL 启动时创建不了 socket 文件。

### 解决
见坑 2 的解决——先建目录再启动。

或者用 TCP 方式连接（绕开 socket）：
```bash
mysql -h 127.0.0.1 -P 3306 -u root -p
```

---

## 坑 4：root 密码怎么设

### 现象
关了 systemd 后，不知道怎么连 root。

### 解决
MySQL 8 默认 auth_socket 插件，root 用 sudo 身份可以免密进 socket：

```bash
# 启动 MySQL 后，用 socket + sudo 免密进
sudo mysql -u root -S /var/run/mysqld/mysqld.sock

# 在 MySQL 里设密码
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '你的强口令';
```

---

## WSL MySQL 启动标准操作（脚本化）

每次 WSL 重启后，按这个顺序来：

```bash
#!/bin/bash
# wsl-mysql-start.sh

# 1. 创建运行目录（/var/run 每次重启清空）
sudo mkdir -p /var/run/mysqld
sudo chown mysql:mysql /var/run/mysqld

# 2. 启动 Redis（用 service 方式没问题）
sudo service redis-server start

# 3. 启动 MySQL（mysqld_safe 后台）
if ! pgrep -x mysqld > /dev/null; then
    sudo mysqld_safe --datadir=/var/lib/mysql --pid-file=/var/run/mysqld/mysqld.pid &
    echo "MySQL 启动中，等待就绪..."
    for i in {1..15}; do
        if sudo mysqladmin ping -S /var/run/mysqld/mysqld.sock --silent 2>/dev/null; then
            echo "MySQL 就绪（$((i*2))s）"
            break
        fi
        sleep 2
    done
else
    echo "MySQL 已在运行"
fi
```

---

## 经验总结

| 项 | 推荐做法 | 不推荐 |
|----|---------|--------|
| 初始化方式 | `mysqld_safe` 手动起 | 依赖 systemd |
| 连接方式 | socket（本机）或 TCP（127.0.0.1） | 用 `localhost`（会走 socket 文件，可能路径不一致） |
| 数据目录 | `/var/lib/mysql`（WSL 本地 ext4） | 不要放 /mnt/c 或 /mnt/e（NTFS 性能差 + 权限问题） |
| 每次 WSL 重启 | 先建 /var/run/mysqld 目录，再启 mysqld | 直接 `service mysql start` |
| WSL 配置 | `systemd=false` + `metadata` 挂载选项 | systemd=true（不稳定） |

---

## 坑 5：root 密码设了之后忘了，怎么找回 / 重置

### 现象
`ALTER USER 'root'@'localhost' IDENTIFIED BY ...` 执行后没存密码，之后连不上 root。

### 解决
两种方式：

**方式一：socket + auth_socket 免密（推荐，最快）**

MySQL 8 默认 root @ localhost 用 auth_socket 插件时，sudo 身份可以直接免密进 socket。
即使你用 `ALTER USER ... IDENTIFIED WITH caching_sha2_password` 改了密码，WSL 下很多时候 socket 连接仍能用 sudo 进（取决于 MySQL 版本和配置）。

```bash
sudo mysql -u root -S /var/run/mysqld/mysqld.sock
```

如果能进去，直接重置密码：
```sql
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '新口令';
FLUSH PRIVILEGES;
```

**方式二：--skip-grant-tables 重置（万能方案）**

```bash
# 1. 停掉 MySQL
sudo mysqladmin shutdown -S /var/run/mysqld/mysqld.sock
# 或者直接杀进程：sudo pkill mysqld

# 2. 跳过权限表启动
sudo mysqld_safe --datadir=/var/lib/mysql --skip-grant-tables --skip-networking &

# 3. 免密进，刷新权限表，改密码
mysql -u root -S /var/run/mysqld/mysqld.sock
```

```sql
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '新口令';
FLUSH PRIVILEGES;
EXIT;
```

```bash
# 4. 正常重启
sudo mysqladmin shutdown -S /var/run/mysqld/mysqld.sock
# 再用 mysqld_safe 正常启动
```

### 教训
**任何 DML 改密码的操作，改完立即把密码存到凭据文件或密码管理器**，不要靠脑子记。

---

## 坑 6：demo_sched 用户 TCP 连接卡住 / 超时

### 现象
用户建好了，库也有，但 `mysql -h 127.0.0.1 -u demo_sched -pxxxx demo_scheduling` 一直卡住不返回。

### 可能原因
1. MySQL 的 `caching_sha2_password` 插件需要 SSL 连接，客户端没 SSL 证书会卡住
2. 防火墙 / iptables 阻断了 127.0.0.1 的 TCP（WSL 一般不会，但保险起见检查）

### 解决
**方式一：连接时加 SSL 参数**
```bash
mysql -h 127.0.0.1 -u demo_sched -p --ssl-mode=required demo_scheduling
```

**方式二：把认证插件改成 mysql_native_password（兼容旧客户端）**
```sql
ALTER USER 'demo_sched'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '口令';
FLUSH PRIVILEGES;
```

> 本项目用 pymysql 连接，默认支持 caching_sha2_password，一般不需要改。
