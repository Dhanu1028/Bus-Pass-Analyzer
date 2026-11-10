
CREATE TABLE student_registration (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    contact_number VARCHAR(20) NOT NULL,
    address TEXT NOT NULL,
    arrival_stop VARCHAR(100) NOT NULL,
    destination_stop VARCHAR(100) NOT NULL,
    bus_pass_validity VARCHAR(50) NOT NULL,
    payment_receipt TEXT, 
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

SELECT * FROM student_registration;
SELECT * FROM student_registration ORDER BY created_at DESC;
SELECT COUNT(*) FROM student_registration;

