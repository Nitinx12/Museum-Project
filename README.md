### **SQL Analysis: Exploring Famous Paintings**

Hey\! I'm Nitin, an MBA student at the University of Delhi. I'm passionate about using data to find interesting stories, and this project was a fun way for me to practice my SQL skills on a dataset about famous art.

#### **About This Project**

I took a dataset with info on paintings, artists, and museums and decided to see what I could uncover. Instead of just pulling tables, I wanted to answer real questions.

A couple of cool things I found:

* A small handful of world-famous museums hold a surprisingly large share of the art pieces in the dataset.  
* When it comes to a painting's price, the artist's reputation often matters much more than the actual size of the canvas.

This was a great exercise in using advanced SQL, like CTEs and window functions, to connect the dots and pull out these insights.

#### **How to Run It**

If you want to explore the data yourself, it's pretty simple:

1. **You'll need:** Python and a PostgreSQL database.  
2. **Setup:** Clone the project, place the CSV files in a `Dataset/` folder, and update the database connection details in the `load_csv_files.py` script.  
3. **Load:** Run the Python script to load all the data into your database.  
4. **Query:** You're all set\! You can now use the queries in `project.sql` to start analyzing.

#### **Tech I Used**

* **Languages:** SQL, Python  
* **Database:** PostgreSQL  
* **Libraries:** Pandas, SQLAlchemy

