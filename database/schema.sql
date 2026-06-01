-- Rus-Ukr Intel Visualization clean schema
-- MySQL 8.0+. This script initializes an empty database for demonstration/review.
-- It intentionally does not include local AUTO_INCREMENT values or imported data.

CREATE DATABASE IF NOT EXISTS `rus_ukr_analysis`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `rus_ukr_analysis`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `chunk_embeddings`;
DROP TABLE IF EXISTS `query_history`;
DROP TABLE IF EXISTS `weibo_event_links`;
DROP TABLE IF EXISTS `evidences`;
DROP TABLE IF EXISTS `event_entity_links`;
DROP TABLE IF EXISTS `relations`;
DROP TABLE IF EXISTS `entities`;
DROP TABLE IF EXISTS `public_opinion_posts`;
DROP TABLE IF EXISTS `conflict_events`;
DROP TABLE IF EXISTS `document_chunks`;
DROP TABLE IF EXISTS `documents`;
DROP TABLE IF EXISTS `workspaces`;

CREATE TABLE `workspaces` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `description` TEXT NULL,
  `theme` VARCHAR(255) NULL DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_workspaces_theme` (`theme`),
  KEY `idx_workspaces_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `documents` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `title` VARCHAR(500) NOT NULL,
  `source_name` VARCHAR(255) NULL DEFAULT NULL,
  `source_type` VARCHAR(100) NULL DEFAULT NULL COMMENT 'acled,weibo,news,official,report',
  `file_type` VARCHAR(50) NULL DEFAULT NULL COMMENT 'csv,txt,pdf,docx,json',
  `file_path` VARCHAR(1000) NULL DEFAULT NULL,
  `url` VARCHAR(1000) NULL DEFAULT NULL,
  `published_at` DATETIME NULL DEFAULT NULL,
  `language` VARCHAR(50) NULL DEFAULT NULL,
  `country_related` VARCHAR(100) NULL DEFAULT NULL,
  `status` VARCHAR(50) NULL DEFAULT 'pending' COMMENT 'pending,processed,failed',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_documents_workspace_created` (`workspace_id`, `created_at`),
  KEY `idx_documents_status` (`workspace_id`, `status`),
  KEY `idx_documents_file_type` (`workspace_id`, `file_type`),
  CONSTRAINT `fk_documents_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `document_chunks` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `document_id` BIGINT NOT NULL,
  `chunk_index` INT NOT NULL,
  `text` LONGTEXT NOT NULL,
  `token_count` INT NULL DEFAULT NULL,
  `page_no` INT NULL DEFAULT NULL,
  `source_path` VARCHAR(1000) NULL DEFAULT NULL,
  `file_modified_at` DATETIME NULL DEFAULT NULL,
  `start_offset` INT NULL DEFAULT NULL,
  `end_offset` INT NULL DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_document_chunk` (`document_id`, `chunk_index`),
  KEY `idx_chunks_document_created` (`document_id`, `created_at`),
  CONSTRAINT `fk_chunks_document`
    FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `conflict_events` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `event_code` VARCHAR(50) NOT NULL COMMENT 'ACLED event_id_cnty',
  `event_date` DATE NOT NULL,
  `event_date_raw` VARCHAR(100) NULL DEFAULT NULL,
  `year` INT NULL DEFAULT NULL,
  `time_precision` INT NULL DEFAULT NULL,
  `disorder_type` VARCHAR(100) NULL DEFAULT NULL,
  `event_type` VARCHAR(100) NULL DEFAULT NULL,
  `sub_event_type` VARCHAR(100) NULL DEFAULT NULL,
  `actor1_name` VARCHAR(255) NULL DEFAULT NULL,
  `actor1_assoc` VARCHAR(255) NULL DEFAULT NULL,
  `actor1_type` VARCHAR(100) NULL DEFAULT NULL,
  `actor2_name` VARCHAR(255) NULL DEFAULT NULL,
  `actor2_assoc` VARCHAR(255) NULL DEFAULT NULL,
  `actor2_type` VARCHAR(100) NULL DEFAULT NULL,
  `interaction_type` VARCHAR(255) NULL DEFAULT NULL,
  `civilian_targeting` VARCHAR(100) NULL DEFAULT NULL,
  `iso_code` INT NULL DEFAULT NULL,
  `region` VARCHAR(100) NULL DEFAULT NULL,
  `country` VARCHAR(100) NULL DEFAULT NULL,
  `admin1` VARCHAR(100) NULL DEFAULT NULL,
  `admin2` VARCHAR(100) NULL DEFAULT NULL,
  `admin3` VARCHAR(100) NULL DEFAULT NULL,
  `location_name` VARCHAR(255) NULL DEFAULT NULL,
  `latitude` DECIMAL(10,6) NULL DEFAULT NULL,
  `longitude` DECIMAL(10,6) NULL DEFAULT NULL,
  `geo_precision` INT NULL DEFAULT NULL,
  `source_name` VARCHAR(500) NULL DEFAULT NULL,
  `source_scale` VARCHAR(100) NULL DEFAULT NULL,
  `notes` LONGTEXT NULL,
  `fatalities` INT NULL DEFAULT 0,
  `tags` TEXT NULL,
  `source_timestamp` BIGINT NULL DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_conflict_event_code` (`event_code`),
  KEY `idx_conflict_workspace_id` (`workspace_id`, `id`),
  KEY `idx_conflict_workspace_code` (`workspace_id`, `event_code`),
  KEY `idx_conflict_workspace_date` (`workspace_id`, `event_date`),
  KEY `idx_conflict_workspace_year_date` (`workspace_id`, `year`, `event_date`),
  KEY `idx_conflict_workspace_admin_date` (`workspace_id`, `admin1`, `event_date`),
  KEY `idx_conflict_workspace_type_date` (`workspace_id`, `event_type`, `event_date`),
  KEY `idx_conflict_workspace_actor1` (`workspace_id`, `actor1_name`),
  KEY `idx_conflict_workspace_actor2` (`workspace_id`, `actor2_name`),
  KEY `idx_conflict_workspace_source` (`workspace_id`, `source_name`),
  FULLTEXT KEY `ft_conflict_text` (`notes`, `actor1_name`, `actor2_name`, `location_name`),
  CONSTRAINT `fk_conflict_events_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `public_opinion_posts` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `row_index` BIGINT NULL DEFAULT NULL,
  `created_at_raw` VARCHAR(100) NULL DEFAULT NULL,
  `created_at_dt` DATETIME NULL DEFAULT NULL,
  `pub_time_raw` VARCHAR(255) NULL DEFAULT NULL,
  `pub_time_dt` DATETIME NULL DEFAULT NULL,
  `msg_id` VARCHAR(80) NOT NULL,
  `text` LONGTEXT NOT NULL,
  `text_length` INT NULL DEFAULT NULL,
  `source_device` VARCHAR(255) NULL DEFAULT NULL,
  `favorited` TINYINT(1) NULL DEFAULT 0,
  `reposts_count` INT NULL DEFAULT 0,
  `comments_count` INT NULL DEFAULT 0,
  `attitudes_count` INT NULL DEFAULT 0,
  `pending_approval_count` INT NULL DEFAULT 0,
  `is_long_text` TINYINT(1) NULL DEFAULT 0,
  `content_auth` INT NULL DEFAULT 0,
  `user_id` VARCHAR(50) NULL DEFAULT NULL,
  `screen_name` VARCHAR(255) NULL DEFAULT NULL,
  `gender` VARCHAR(20) NULL DEFAULT NULL,
  `statuses_count` INT NULL DEFAULT 0,
  `verified` TINYINT(1) NULL DEFAULT 0,
  `verified_type` INT NULL DEFAULT -1,
  `follow_count` INT NULL DEFAULT 0,
  `followers_count_raw` VARCHAR(50) NULL DEFAULT NULL,
  `followers_count_num` BIGINT NULL DEFAULT NULL,
  `description` TEXT NULL,
  `created_ts` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_ts` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_public_posts_msg_id` (`msg_id`),
  KEY `idx_public_posts_workspace_id` (`workspace_id`, `id`),
  KEY `idx_public_posts_workspace_created` (`workspace_id`, `created_at_dt`),
  KEY `idx_public_posts_workspace_screen` (`workspace_id`, `screen_name`),
  FULLTEXT KEY `ft_public_posts_text` (`text`, `screen_name`),
  CONSTRAINT `fk_public_posts_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `entities` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `normalized_name` VARCHAR(255) NOT NULL,
  `entity_type` VARCHAR(100) NOT NULL COMMENT 'actor,location,country,organization,person,weapon,topic',
  `source_origin` VARCHAR(100) NOT NULL DEFAULT 'manual' COMMENT 'acled,news,weibo,manual',
  `description` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_entities_workspace_norm_type_origin`
    (`workspace_id`, `normalized_name`, `entity_type`, `source_origin`),
  KEY `idx_entities_workspace_type` (`workspace_id`, `entity_type`),
  KEY `idx_entities_workspace_origin` (`workspace_id`, `source_origin`),
  CONSTRAINT `fk_entities_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `relations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `source_entity_id` BIGINT NOT NULL,
  `target_entity_id` BIGINT NOT NULL,
  `relation_type` VARCHAR(100) NOT NULL,
  `description` TEXT NULL,
  `confidence` DECIMAL(5,4) NULL DEFAULT 1.0000,
  `source_origin` VARCHAR(100) NOT NULL DEFAULT 'manual' COMMENT 'news,weibo,manual,derived,acled',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_relations_workspace_source_target_type_origin`
    (`workspace_id`, `source_entity_id`, `target_entity_id`, `relation_type`, `source_origin`),
  KEY `idx_relations_workspace_type` (`workspace_id`, `relation_type`),
  KEY `idx_relations_source_entity` (`source_entity_id`),
  KEY `idx_relations_target_entity` (`target_entity_id`),
  CONSTRAINT `fk_relations_source_entity`
    FOREIGN KEY (`source_entity_id`) REFERENCES `entities` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_relations_target_entity`
    FOREIGN KEY (`target_entity_id`) REFERENCES `entities` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_relations_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `event_entity_links` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `event_id` BIGINT NOT NULL,
  `entity_id` BIGINT NOT NULL,
  `role_type` VARCHAR(100) NOT NULL COMMENT 'actor1,actor2,location,source,civilian_group,mentioned',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_event_entity_role` (`event_id`, `entity_id`, `role_type`),
  KEY `idx_event_entity_links_entity` (`entity_id`),
  KEY `idx_event_entity_links_role` (`role_type`),
  CONSTRAINT `fk_event_entity_links_entity`
    FOREIGN KEY (`entity_id`) REFERENCES `entities` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_event_entity_links_event`
    FOREIGN KEY (`event_id`) REFERENCES `conflict_events` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `evidences` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `evidence_type` VARCHAR(100) NOT NULL COMMENT 'document_chunk,acled_note,weibo_post,relation_support,answer_support',
  `document_id` BIGINT NULL DEFAULT NULL,
  `chunk_id` BIGINT NULL DEFAULT NULL,
  `event_id` BIGINT NULL DEFAULT NULL,
  `post_id` BIGINT NULL DEFAULT NULL,
  `entity_id` BIGINT NULL DEFAULT NULL,
  `relation_id` BIGINT NULL DEFAULT NULL,
  `quote_text` LONGTEXT NULL,
  `source_label` VARCHAR(255) NULL DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_evidences_workspace_type` (`workspace_id`, `evidence_type`),
  KEY `idx_evidences_document` (`document_id`),
  KEY `idx_evidences_chunk` (`chunk_id`),
  KEY `idx_evidences_event` (`event_id`),
  KEY `idx_evidences_post` (`post_id`),
  KEY `idx_evidences_entity` (`entity_id`),
  KEY `idx_evidences_relation` (`relation_id`),
  CONSTRAINT `fk_evidences_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_evidences_document`
    FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_evidences_chunk`
    FOREIGN KEY (`chunk_id`) REFERENCES `document_chunks` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_evidences_event`
    FOREIGN KEY (`event_id`) REFERENCES `conflict_events` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_evidences_post`
    FOREIGN KEY (`post_id`) REFERENCES `public_opinion_posts` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_evidences_entity`
    FOREIGN KEY (`entity_id`) REFERENCES `entities` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_evidences_relation`
    FOREIGN KEY (`relation_id`) REFERENCES `relations` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `weibo_event_links` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `post_id` BIGINT NOT NULL,
  `event_id` BIGINT NOT NULL,
  `link_method` VARCHAR(100) NULL DEFAULT NULL COMMENT 'keyword,date_window,llm_match,manual',
  `confidence` DECIMAL(5,4) NULL DEFAULT 1.0000,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_weibo_event_link` (`post_id`, `event_id`),
  KEY `idx_weibo_event_links_event` (`event_id`),
  CONSTRAINT `fk_weibo_event_links_post`
    FOREIGN KEY (`post_id`) REFERENCES `public_opinion_posts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_weibo_event_links_event`
    FOREIGN KEY (`event_id`) REFERENCES `conflict_events` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `query_history` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `workspace_id` BIGINT NOT NULL,
  `query_text` TEXT NOT NULL,
  `query_mode` VARCHAR(100) NULL DEFAULT NULL COMMENT 'global,local,event_chain,evidence',
  `answer_text` LONGTEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_query_history_workspace_created` (`workspace_id`, `created_at`),
  CONSTRAINT `fk_query_history_workspace`
    FOREIGN KEY (`workspace_id`) REFERENCES `workspaces` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `chunk_embeddings` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `document_id` BIGINT NOT NULL,
  `chunk_id` BIGINT NOT NULL,
  `model` VARCHAR(255) NOT NULL,
  `dimension` INT NOT NULL,
  `embedding_json` LONGTEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chunk_embedding_model` (`chunk_id`, `model`),
  KEY `idx_chunk_embeddings_document` (`document_id`),
  KEY `idx_chunk_embeddings_chunk` (`chunk_id`),
  CONSTRAINT `fk_chunk_embeddings_document`
    FOREIGN KEY (`document_id`) REFERENCES `documents` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_chunk_embeddings_chunk`
    FOREIGN KEY (`chunk_id`) REFERENCES `document_chunks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET FOREIGN_KEY_CHECKS = 1;
