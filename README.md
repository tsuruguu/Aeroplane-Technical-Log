# Aeroplane Technical Log (PDT) ✈️

**Aeroplane Technical Log** is a professional-grade ERP solution designed for aeroclubs and aviation organizations to digitize flight logging, fleet management, and financial settlements. 

The system serves as a modern, super secure, and real-time alternative to traditional paper-based journey logs, ensuring data integrity and operational efficiency.

---

## 🌟 Key Modules

The application is built with a modular architecture, allowing for precise management of different aviation business processes:

### 1. Flight Operations Management (`flights`)
* **Digital Logbook**: Streamlined interface for adding, editing, and reviewing flight entries.
* **Time Tracking**: Precise monitoring of flight hours for aircraft, gliders, and pilots.
* **Validation**: Built-in logic to prevent entry errors common in paper logs.

### 2. Technical & Maintenance Module (`mechanic`)
* **Mechanic Dashboard**: A central hub for monitoring the technical status of the entire fleet.
* **Aircraft Profiles**: Detailed records for airplanes and gliders, including technical specifications.
* **Maintenance Alerts**: Tracks inspection intervals (e.g., 50h/100h checks, ARC) and insurance expiries.

### 3. Financial & Reporting Module (`reports`)
* **Financial Analytics**: Automated generation of flight cost reports and settlements.
* **Operational Statistics**: Comprehensive dashboards showing aeroclub activity over specific periods.
* **Pilot Billing**: Rapid data export for internal invoicing and member settlements.

### 4. Administration & Security (`admin` & `auth`)
* **User Management**: Advanced admin panel to manage member data and roles.
* **Access Control**: Secure login and registration system with role-based permissions (Pilot, Mechanic, Administrator).
* **Profile Management**: Personalized user settings and individual flight history access.

---

## 🛠️ Technology Stack

The project utilizes a robust and scalable stack designed for reliability:

* **Backend**: [Python](https://www.python.org/) + [Flask](https://flask.palletsprojects.com/) (high-performance micro-framework).
* **Database**: [PostgreSQL](https://www.postgresql.org/) (relational database ensuring data consistency for aviation records).
* **Frontend**: HTML5, CSS3, Jinja2 (responsive templates optimized for both desktop and mobile use).
* **Architecture**: Modular design using Flask Blueprints for maintainability and scalability.

---

## 📂 Project Structure

```text
PDT/
├── routes/              # Business logic modules (admin, auth, flights, mechanic, reports)
├── templates/           # Presentation layer - dynamic HTML templates
├── static/              # Static assets (CSS styles, JS scripts, images)
├── docs/                # Technical documentation and project manuals
├── app.py               # Main application entry point and configuration
├── models.py            # Database schema and SQLAlchemy models
├── database.py          # Database engine and session configuration
├── extensions.py        # Flask extension initializations
└── requirements.txt     # List of project dependencies
```

---

## ⚖️ License & Copyright

### Copyright (c) 2024-2026 tsuruguu. All rights reserved.
This project is Proprietary Software. The source code and all associated assets are fully protected by copyright law.
* **No Redistribution**: Copying, modifying, distributing, or using this code in any form without the express written permission of the author is strictly prohibited.
* **Commercial Use**: This project is intended for commercial deployment. For licensing inquiries, please contact the author directly.

---
*Developed with a focus on technical precision and the specific needs of the aviation community.*



