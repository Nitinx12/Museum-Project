-- Fetch all the paintings which are not displayed on any museums?

SELECT *
FROM work WHERE museum_id IS NULL

-- Are there museuems without any paintings?

SELECT *
FROM museum AS M
LEFT JOIN work AS W ON
W.museum_id = M.museum_id
WHERE W.museum_id IS NULL

-- How many paintings have an asking price of more than their regular price?

SELECT *
FROM product_size
WHERE sale_price > regular_price

-- Which canva size costs the most?

WITH T1 AS(SELECT CS.label AS canva_size, PS.sale_price AS costs,
			DENSE_RANK() OVER(ORDER BY PS.sale_price DESC) AS rnk
			FROM canvas_size AS CS
			INNER JOIN product_size AS PS ON
			PS.size_id = CS.size_id :: TEXT)

SELECT *
FROM T1
WHERE rnk = 1

-- Delete duplicate records from work, product_size, subject and image_link tables

-- FOR work
WITH T1 AS(SELECT work_id,
		ROW_NUMBER() OVER(PARTITION BY name, artist_id, style ORDER BY work_id) AS rnk
		FROM work)

DELETE FROM work
WHERE work_id IN (SELECT work_id FROM T1 WHERE rnk > 1)

-- FOR product_size
WITH T1 AS(SELECT size_id,
		ROW_NUMBER() OVER(PARTITION BY sale_price, regular_price ORDER BY size_id) AS rnk
		FROM product_size)

DELETE FROM product_size
WHERE size_id IN (SELECT size_id FROM T1 WHERE rnk > 1)


-- FOR subject
DELETE FROM subject 
WHERE ctid NOT IN (SELECT MIN(ctid)
					FROM subject
					GROUP BY work_id, subject)
-- FOR image_ink

DELETE FROM image_link 
WHERE ctid NOT IN (SELECT MIN(ctid)
					FROM image_link
					GROUP BY work_id)

-- Identify the museums with invalid city information in the given dataset

SELECT *
FROM museum
WHERE city ~ '^[0-9]'

-- Museum_Hours table has 1 invalid entry. Identify it and remove it.

DELETE FROM museum_hours 
WHERE ctid NOT IN (SELECT MIN(ctid)
					FROM museum_hours
					GROUP BY museum_id, day )

-- Fetch the top 10 most famous painting subject

WITH T1 AS (
SELECT S.subject, COUNT(1) AS no_of_painting,
DENSE_RANK() OVER(ORDER BY COUNT(1) DESC) AS ranking
FROM subject AS S
INNER JOIN work AS W ON
S.work_id = W.work_id
GROUP BY 1)

SELECT *
FROM T1
WHERE ranking <= 10

-- Identify the museums which are open on both Sunday and Monday. Display museum name, city

SELECT M.name, M.city, M.state, M.country
FROM museum AS M
JOIN museum_hours AS MH ON
M.museum_id = MH.museum_id
WHERE MH.day IN ('Sunday', 'Monday')
GROUP BY 1, 2, 3, 4
HAVING COUNT(DISTINCT MH.day) = 2

-- How many museums are open every single day?

SELECT M.name
FROM museum_hours AS MH
INNER JOIN museum AS M ON
M.museum_id = MH.museum_id
GROUP BY 1
HAVING COUNT(MH.museum_id) = 7

--  Which are the top 5 most popular museum? (Popularity is defined based on most no of paintings in a museum)

SELECT M.name AS museum, M.city, M.country,
X.no_of_painting
FROM (SELECT M.museum_id, COUNT(1) AS no_of_painting,
	RANK() OVER(ORDER BY COUNT(1) DESC) AS rnk
	FROM work AS W
	INNER JOIN museum AS M ON
	M.museum_id = W.museum_id
	GROUP BY 1) AS X
INNER JOIN museum AS M ON
M.museum_id = X.museum_id
WHERE X.rnk <= 5

-- Who are the top 5 most popular artist? (Popularity is defined based on most no of paintings done by an artist)

SELECT A.full_name, X.no_of_painting
FROM (SELECT A.artist_id, COUNT(1) AS no_of_painting,
	RANK() OVER(ORDER BY COUNT(1) DESC) AS rnk
	FROM artist AS A
	INNER JOIN work AS W ON
	A.artist_id = W.artist_id
	GROUP BY 1) AS X
INNER JOIN artist AS A ON
A.artist_id = X.artist_id
WHERE rnk <= 5

-- Display the 3 least popular canva sizes

SELECT X.label, X.rnk, X.no_of_paintings
FROM	(SELECT CS.size_id, CS.label, COUNT(1) AS no_of_paintings,
		DENSE_RANK() OVER(ORDER BY COUNT(1) ASC) AS rnk
		FROM work AS W
		INNER JOIN product_size AS PS ON
		PS.work_id = W.work_id
		INNER JOIN canvas_size AS CS ON 
		CAST(CS.size_id AS TEXT) = PS.size_id
		GROUP BY 1, 2) AS X
WHERE X.no_of_paintings <= 3

-- Which museum has the most no of most popular painting style?

with pop_style as 
			(select style
			,rank() over(order by count(1) desc) as rnk
			from work
			group by style),
		cte as
			(select w.museum_id,m.name as museum_name,ps.style, count(1) as no_of_paintings
			,rank() over(order by count(1) desc) as rnk
			from work w
			join museum m on m.museum_id=w.museum_id
			join pop_style ps on ps.style = w.style
			where w.museum_id is not null
			and ps.rnk=1
			group by w.museum_id, m.name,ps.style)
	select museum_name,style,no_of_paintings
	from cte 
	where rnk=1;

-- Identify the artists whose paintings are displayed in multiple countries

with cte as
		(select distinct a.full_name as artist
		--, w.name as painting, m.name as museum
		, m.country
		from work w
		join artist a on a.artist_id=w.artist_id
		join museum m on m.museum_id=w.museum_id)
	select artist,count(1) as no_of_countries
	from cte
	group by artist
	having count(1)>1
	order by 2 desc;

-- Display the country and the city with most no of museums. Output 2 seperate columns to mention the city and country. If there are multiple value, seperate them with comma.

with cte_country as 
			(select country, count(1)
			, rank() over(order by count(1) desc) as rnk
			from museum
			group by country),
		cte_city as
			(select city, count(1)
			, rank() over(order by count(1) desc) as rnk
			from museum
			group by city)
	select string_agg(distinct country.country,', '), string_agg(city.city,', ')
	from cte_country country
	cross join cte_city city
	where country.rnk = 1
	and city.rnk = 1;

-- Identify the artist and the museum where the most expensive and least expensive painting is placed. 
-- Display the artist name, sale_price, painting name, museum name, museum city and canvas label

with cte as 
		(select *
		, rank() over(order by sale_price desc) as rnk
		, rank() over(order by sale_price ) as rnk_asc
		from product_size )
	select w.name as painting
	, cte.sale_price
	, a.full_name as artist
	, m.name as museum, m.city
	, cz.label as canvas
	from cte
	join work w on w.work_id=cte.work_id
	join museum m on m.museum_id=w.museum_id
	join artist a on a.artist_id=w.artist_id
	join canvas_size cz on cz.size_id = cte.size_id::NUMERIC
	where rnk=1 or rnk_asc=1;













