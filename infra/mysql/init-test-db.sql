-- 仅用于本地开发：测试库独立于应用库，避免测试改动正式迁移版本。
CREATE DATABASE IF NOT EXISTS score_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON score_test.* TO 'score'@'%';
