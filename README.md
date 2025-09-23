

---

# **SQL Case Study: Analysis of Famous Paintings**

## **Overview**

This project is an in-depth analysis of a dataset containing information about famous paintings, artists, and museums. Using SQL, we explore the data to answer 22 specific business and analytical questions. The primary goal is to demonstrate proficiency in SQL for data cleaning, validation, and complex querying, including the use of joins, aggregate functions, window functions, and Common Table Expressions (CTEs).

The entire workflow involves:

1. Loading raw data from multiple CSV files into a PostgreSQL database using a Python script.  
2. Executing a series of SQL queries to solve challenges ranging from simple data retrieval to complex analytical problems.

## **Dataset**

The dataset is normalized and distributed across eight distinct CSV files, which correspond to the tables in our database:

* `artist`: Contains details about the artists (e.g., name, nationality).  
* `canvas_size`: Information about different canvas sizes.  
* `image_link`: URLs for the images of the paintings.  
* `museum_hours`: Opening and closing times for museums on different days.  
* `museum`: Details about the museums (e.g., name, city, country).  
* `product_size`: Links paintings to their canvas sizes and includes pricing information like `sale_price` and `regular_price`.  
* `subject`: The subject or genre of each painting.  
* `work`: The central table containing details about each painting, linking artists and museums.

## **Project Setup**

To replicate this analysis, you will need the following prerequisites and setup steps.

### **Prerequisites**

* Python 3.x  
* A running instance of PostgreSQL

The following Python libraries: `pandas`, `sqlalchemy`, and `psycopg2-binary`. You can install them using pip:  
Bash  
pip install pandas sqlalchemy psycopg2-binary

* 

### **Installation and Setup**

1. **Clone the Repository:** Download or clone this project to your local machine.  
2. **Prepare the Dataset:** Place all the CSV files (`artist.csv`, `work.csv`, etc.) into a single directory named `Dataset/`.  
3. **Configure the Database Connection:**  
   * Open the `load_csv_files.py` script.

Update the `conn_string` variable with your own PostgreSQL credentials:  
Python  
\# Format: 'postgresql://user:password@host/database\_name'  
conn\_string \= 'postgresql://your\_user:your\_password@localhost/painting'

* 

Update the file path in the `pd.read_csv()` function to point to the location of your `Dataset/` folder.  
Python  
\# Update this path  
df \= pd.read\_csv(f'/path/to/your/Dataset/{file}.csv')

* 

**Load the Data:** Run the Python script from your terminal to create the tables and load the data into your PostgreSQL database.  
Bash  
python load\_csv\_files.py

4.   
5. **Run the SQL Queries:** The database is now ready. You can use a SQL client of your choice (like DBeaver, pgAdmin, or the `psql` command line) to connect to your `painting` database and execute the queries found in the `project.sql` file.

## **Case Study Questions**

The analysis is driven by the questions outlined in the `SQL Paintings Casestudy - Questions.pdf` file. These questions are designed to test a variety of SQL skills and cover several analytical areas:

#### **Data Cleaning and Validation**

* Deleting duplicate records from tables.  
* Identifying and removing invalid entries in museum hours.  
* Finding museums with improperly formatted city names.

#### **Museum-Specific Analysis**

* Finding museums without any paintings.  
* Identifying which museums are open on both Sunday and Monday.  
* Calculating which museums are open every day of the week.  
* Determining the top 5 most popular museums based on painting count.  
* Finding the museum that is open for the longest duration in a single day.

#### **Artist and Painting Analysis**

* Fetching paintings not displayed in any museum.  
* Identifying paintings with an asking price higher than their regular price.  
* Finding the top 10 most famous painting subjects.  
* Identifying the top 5 most popular artists.  
* Determining which country has the 5th highest number of paintings.  
* Finding the artist with the most "Portrait" style paintings outside of the USA.

#### **Financial and Popularity Analysis**

* Finding the most expensive canvas size.  
* Identifying the 3 least popular canvas sizes.  
* Displaying the most and least expensive paintings along with their artist and museum details.  
* Determining the 3 most popular and 3 least popular painting styles.

## **Example Query Spotlight**

To showcase the complexity of the analysis, here is the query used to find the museum which has the most paintings of the most popular painting style. This query uses multiple CTEs and window functions to break the problem down.

**Question:** Which museum has the most number of the most popular painting style?

SQL  
WITH pop\_style AS (  
    \-- First, find the most popular style using RANK()  
    SELECT  
        style,  
        RANK() OVER(ORDER BY COUNT(1) DESC) AS rnk  
    FROM work  
    GROUP BY style  
),  
cte AS (  
    \-- Next, count paintings of that popular style for each museum  
    SELECT  
        w.museum\_id,  
        m.name AS museum\_name,  
        ps.style,  
        COUNT(1) AS no\_of\_paintings,  
        RANK() OVER(ORDER BY COUNT(1) DESC) AS rnk  
    FROM work w  
    JOIN museum m ON m.museum\_id \= w.museum\_id  
    JOIN pop\_style ps ON ps.style \= w.style  
    WHERE w.museum\_id IS NOT NULL  
      AND ps.rnk \= 1 \-- Filter for only the most popular style  
    GROUP BY w.museum\_id, m.name, ps.style  
)  
\-- Finally, select the museum with the highest rank  
SELECT museum\_name, style, no\_of\_paintings  
FROM cte  
WHERE rnk \= 1;

## **Technologies Used**

* **Database:** PostgreSQL  
* **Language:** Python 3 & SQL  
* **Libraries:** Pandas, SQLAlchemy

# Museum-Project
