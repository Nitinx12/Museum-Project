# Data Catalog — Gold Layer

This document defines the business logic, field descriptions, and grain for the Gold layer models. The Gold layer provides a star-schema optimized for business intelligence and reporting.

## 1. Fact Table: `fct_sales`
**Grain**: One row per unique combination of artwork (`work_id`) and canvas size (`size_id`).

| Column | Type | Description | Constraints |
|---|---|---|---|
| `sales_key` | TEXT | Surrogate primary key (`work_id` + `size_id`). | PK, Unique, Not Null |
| `work_id` | INT | Foreign Key to `dim_artwork`. | FK, Not Null |
| `artist_id` | INT | Foreign Key to `dim_artist`. | FK, Nullable |
| `museum_id` | INT | Foreign Key to `dim_museum`. | FK, Nullable |
| `size_id` | INT | Foreign Key to `dim_canvas_size`. | FK, Not Null |
| `sale_price` | NUMERIC | Discounted sale price in source currency. | Not Null |
| `regular_price` | NUMERIC | Full list price in source currency. | Not Null |
| `discount_amount` | NUMERIC | Calculated as `regular_price` - `sale_price`. | - |
| `discount_pct` | NUMERIC | Calculated as `discount_amount / regular_price`. | - |
| `is_in_museum` | BOOLEAN | `TRUE` if the artwork is currently assigned to a museum. | - |
| `source_updated_at` | TIMESTAMPTZ | The original `updated_at` timestamp from the source. | Not Null |
| `silver_loaded_at` | TIMESTAMPTZ | Watermark from the Silver layer. | Not Null |
| `gold_loaded_at` | TIMESTAMPTZ | Timestamp of the last merge into the Gold layer. | Not Null |

---

## 2. Dimensions

### `dim_artwork`
**Grain**: One row per unique piece of artwork.

| Column | Type | Description | Constraints |
|---|---|---|---|
| `work_id` | INT | Primary key. | PK, Unique, Not Null |
| `artwork_name` | VARCHAR | Full title of the artwork. | Not Null |
| `style` | VARCHAR | Artistic style (e.g., Impressionism). | Nullable |
| `subject_tags` | TEXT | Comma-separated list of tags from the `subject` source table. | Not Null |
| `artist_id` | INT | Foreign Key to `dim_artist`. | FK, Nullable |
| `museum_id` | INT | Foreign Key to `dim_museum`. | FK, Nullable |
| `silver_loaded_at` | TIMESTAMPTZ | Watermark from the Silver layer. | Not Null |
| `gold_loaded_at` | TIMESTAMPTZ | Timestamp of the last merge into the Gold layer. | Not Null |

### `dim_artist`
**Grain**: One row per unique artist.

| Column | Type | Description | Constraints |
|---|---|---|---|
| `artist_id` | INT | Primary key. | PK, Unique, Not Null |
| `artist_name` | VARCHAR | Full name (First, Middle, Last). | Not Null |
| `nationality` | VARCHAR | Artist's nationality. Defaults to 'Unknown'. | Not Null |
| `style` | VARCHAR | Primary artistic style. Defaults to 'Unknown'. | Not Null |
| `birth_year` | INT | Year of birth. | Nullable |
| `death_year` | INT | Year of death. Null if living. | Nullable |
| `era` | VARCHAR | Computed era (e.g., Renaissance, Modern). | Not Null |
| `artist_status` | VARCHAR | 'Historical' (deceased) or 'Living / Unknown'. | Not Null |
| `silver_loaded_at` | TIMESTAMPTZ | Watermark from the Silver layer. | Not Null |
| `gold_loaded_at` | TIMESTAMPTZ | Timestamp of the last merge into the Gold layer. | Not Null |

### `dim_museum`
**Grain**: One row per museum.

| Column | Type | Description | Constraints |
|---|---|---|---|
| `museum_id` | INT | Primary key. | PK, Unique, Not Null |
| `museum_name` | VARCHAR | Full name of the institution. | Not Null |
| `city` | VARCHAR | City location. Defaults to 'Unknown'. | Not Null |
| `state` | VARCHAR | State/Province. | Nullable |
| `country` | VARCHAR | Country. Defaults to 'Unknown'. | Not Null |
| `address` | VARCHAR | Street address. | Not Null |
| `phone` | VARCHAR | Contact phone number. | Unique, Not Null |
| `url` | VARCHAR | Website URL. | Unique, Not Null |
| `opening_days_per_week` | INT | Total days open per week. | Not Null |
| `avg_daily_open_hours` | NUMERIC | Average open duration per day. | Nullable |
| `earliest_open_time` | TIME | Earliest opening time across all days. | - |
| `latest_close_time` | TIME | Latest closing time across all days. | - |
| `is_open_weekends` | BOOLEAN | `TRUE` if open Sat/Sun. | Nullable |
| `silver_loaded_at` | TIMESTAMPTZ | Watermark from the Silver layer. | Not Null |
| `gold_loaded_at` | TIMESTAMPTZ | Timestamp of the last merge into the Gold layer. | Not Null |

### `dim_canvas_size`
**Grain**: One row per unique canvas size definition.

| Column | Type | Description | Constraints |
|---|---|---|---|
| `size_id` | INT | Primary key. | PK, Unique, Not Null |
| `label` | VARCHAR | Human-readable size label. | Not Null |
| `width_inches` | NUMERIC | Width dimension in inches. | - |
| `height_inches` | NUMERIC | Height dimension in inches. | - |
| `area_sq_inches` | NUMERIC | Computed area (`width * height`). | Nullable |
| `size_category` | VARCHAR | Bucket (Small, Medium, Large, Extra Large). | Not Null |
| `silver_loaded_at` | TIMESTAMPTZ | Watermark from the Silver layer. | Not Null |
| `gold_loaded_at` | TIMESTAMPTZ | Timestamp of the last merge into the Gold layer. | Not Null |
