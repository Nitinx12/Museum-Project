# Famous Paintings - SQL Analytics Project

![SQL](https://img.shields.io/badge/Language-SQL-blue.svg)
![Database](https://img.shields.io/badge/Database-PostgreSQL-blue.svg)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## Project Description

This project is a comprehensive SQL-based analysis of a dataset containing information about famous paintings, artists, and museums. The primary goal is to leverage advanced SQL queries to extract meaningful insights from the data. The analysis covers various aspects such as museum operations, artist details, painting subjects, and sales data, demonstrating the power of SQL for data analytics.

---

## Features

-   **Museum Analytics**: Analysis of museum details, including opening hours and locations.
-   **Artist & Painting Insights**: Evaluation of artists based on their work, nationality, and painting styles.
-   **Sales & Market Analysis**: Detailed breakdown of painting sizes, prices, and sales data.
-   **Advanced SQL Queries**: Utilizes CTEs, window functions, and complex joins to answer intricate business questions.

---

## Database Schema

The database consists of several interconnected tables that model the art world's ecosystem.

| Table Name | Description | Key Columns |
|---|---|---|
| `artist` | Stores information about artists, including their full name, nationality, and style. | `artist_id`, `full_name`, `nationality`, `style` |
| `canvas_size` | Contains details about different canvas sizes and their corresponding width and height. | `size_id`, `width`, `height`, `label` |
| `image_link` | Provides URLs for the images of the famous paintings. | `work_id`, `url`, `thumbnail_small_url` |
| `museum` | Contains information about museums, including their name, city, and country. | `museum_id`, `name`, `city`, `country` |
| `museum_hours` | Records the opening hours for each museum on different days of the week. | `museum_id`, `day`, `open`, `close` |
| `product_size` | Stores information about the sale price of paintings based on their size. | `work_id`, `size_id`, `sale_price`, `regular_price` |
| `subject` | Contains details about the subjects or genres of the paintings. | `work_id`, `subject` |
| `work` | The central table containing information about the paintings, including their name, artist, and style. | `work_id`, `name`, `artist_id`, `style`, `museum_id` |

---

## SQL Queries & Analysis

This project answers 20 key analytical questions to provide a comprehensive view of the art dataset.

### 1. Fetch all the paintings which are not displayed in any museums.
```sql
select * from work where museum_id is null;
```

### 2. Are there museums without any paintings?
```sql
select * from museum m
	where not exists (select 1 from work w
					 where w.museum_id = m.museum_id);
```

### 3. How many paintings have an asking price of more than their regular price?
```sql
select * from product_size where sale_price > regular_price;
```

### 4. Identify the paintings whose asking price is less than 50% of its regular price.
```sql
select * from product_size 
	where sale_price < (regular_price*0.5);
```

### 5. Which canva size costs the most?
```sql
select cs.label as canva, ps.sale_price
	from (select *
		  , rank() over(order by sale_price desc) as rnk 
		  from product_size) ps
	join canvas_size cs on cs.size_id=ps.size_id
	where ps.rnk=1;
```

### 6. Delete duplicate records from the work, product_size, subject, and image_link tables.
```sql
-- Solution provided in the SQL file using CTEs and window functions.
```

### 7. Identify the museums which are open on both Sunday and Monday. Display museum name, city.
```sql
select m.name as museum_name, m.city
	from museum_hours mh 
	join museum m on m.museum_id=mh.museum_id
	where day='Sunday'
	and m.museum_id in (select museum_id from museum_hours where day='Monday');
```

### 8. How many museums are open every single day?
```sql
select count(1)
	from (select museum_id, count(1)
		  from museum_hours
		  group by museum_id
		  having count(1) = 7) x;
```

### 9. Which are the top 5 most famous painting subjects?
```sql
select * from (
		select s.subject,count(1) as no_of_paintings
		,rank() over(order by count(1) desc) as rnk
		from work w
		join subject s on s.work_id=w.work_id
		group by s.subject ) x
	where rnk<=5;
```

### 10. Identify the artists whose paintings are displayed in multiple countries.
```sql
-- Solution provided in the SQL file involving joins and grouping.
```

### 11. Display the country and the city with the most no of museums.
```sql
-- Solution provided in the SQL file using CTEs and ranking.
```

### 12. Identify the artist and the museum where the most expensive and cheapest paintings are displayed.
```sql
-- Solution provided in the SQL file using joins and ranking.
```

### 13. Which are the 3 most popular and 3 least popular painting styles?
```sql
-- Solution provided in the SQL file using CTEs, UNION ALL, and ranking.
```

### 14. Which artist has the most no of Portraits paintings outside of America?
```sql
-- Solution provided in the SQL file using joins, filtering, and grouping.
```

### 15. Display the 10 most famous paintings which are not related to "Portraits" or "Still Life".
```sql
-- Solution provided in the SQL file using joins, filtering, and ranking.
```

### 16. Display the name of the museum, its city, and its country for all paintings.
```sql
select w.name as painting, m.name as museum, m.city, m.country
	from work w
	join museum m on m.museum_id=w.museum_id;
```

### 17. Which museum is open for the longest during a day?
```sql
-- Solution provided in the SQL file involving date/time calculations and ranking.
```

### 18. Which museum has the most no of paintings?
```sql
select m.name as museum, count(1) as no_of_paintings
	from work w
	join museum m on m.museum_id=w.museum_id
	group by m.name
	order by 2 desc
	limit 1;
```

### 19. Which museum has the most number of sales?
```sql
select m.name as museum, count(1) as no_of_sales
	from product_size ps
	join work w on w.work_id=ps.work_id
	join museum m on m.museum_id=w.museum_id
	group by m.name
	order by 2 desc
	limit 1;
```

### 20. Who are the top 10 most famous artists?
```sql
select a.full_name, count(1) as no_of_paintings
	from work w
	join artist a on a.artist_id=w.artist_id
	group by a.full_name
	order by 2 desc
	limit 10;
```

---

## Installation & Setup

Follow these steps to set up the project locally.

### Prerequisites
-   PostgreSQL installed and running.
-   Python 3.8+ installed.

### Steps
1.  **Clone the repository:**
    ```sh
    git clone [https://github.com/your-username/famous-paintings-sql.git](https://github.com/your-username/famous-paintings-sql.git)
    cd famous-paintings-sql
    ```

2.  **Install Python libraries:**
    ```sh
    pip install pandas sqlalchemy psycopg2-binary
    ```

3.  **Set up the database:**
    -   Create a new database in PostgreSQL (e.g., `paintings_db`).
    -   Create a user and grant privileges to the database.

4.  **Load the data:**
    -   Place your CSV files in a `data/` directory.
    -   Update the database connection string in the `load_csv_files.py` script:
        ```python
        # Example connection string
        db_url = 'postgresql://user:password@localhost:5432/paintings_db'
        ```
    -   Run the script to create tables and populate them with data:
        ```sh
        python load_csv_files.py
        ```

---

## Technologies Used

| Technology | Description |
|---|---|
| **SQL** | Core language for database querying and analysis. |
| **PostgreSQL** | The relational database management system used to store and manage the data. |
| **Python** | Used for scripting the data loading process into the database. |
| **Pandas** | Python library used to read CSV files and handle data in dataframes. |
| **SQLAlchemy** | Python SQL toolkit and Object Relational Mapper used to connect to the database. |

---

## Key Insights

The analysis of the dataset yielded several key insights:
-   **Museum Operations**: Identified museums open on specific days and those open every day, providing insights into their operational schedules.
-   **Art Popularity**: Determined the most popular painting subjects and styles, highlighting trends in the art world.
-   **Artist Fame**: Ranked artists based on the number of their paintings in the dataset, identifying the most prolific or famous artists.
-   **Market Trends**: Analyzed the pricing of paintings, identifying the most expensive works and the canvas sizes that command the highest prices.

---

## File Structure

```
famous-paintings-sql/
├── data/
│   ├── artist.csv
│   ├── canvas_size.csv
│   ├── image_link.csv
│   ├── museum.csv
│   ├── museum_hours.csv
│   ├── product_size.csv
│   ├── subject.csv
│   └── work.csv
├── project.sql           # Contains all analytical SQL queries
├── load_csv_files.py     # Python script to load CSV data into PostgreSQL
└── README.md             # This file
```

---

## Usage

To reproduce the analysis:

1.  Complete the **Installation & Setup** steps to load the data into your PostgreSQL database.
2.  Connect to your database using a SQL client (e.g., pgAdmin, DBeaver, DataGrip).
3.  Open the `project.sql` file.
4.  Run the queries individually to see the results of each analytical question.

---

## Contributing

Contributions are welcome! If you have suggestions for new analyses or improvements, please follow these steps:

1.  Fork the Project.
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`).
4.  Push to the Branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

Please open an issue first to discuss what you would like to change.

---

## License

This project is distributed under the MIT License. See the `LICENSE` file for more information.
