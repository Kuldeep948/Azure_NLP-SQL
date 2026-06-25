-- ============================================================================
-- 002_insert_data.sql
-- Seed data for all 7 business tables (minimum 50 rows per table)
-- Idempotent: uses MERGE with source temp tables for upsert behavior
-- Target: Azure SQL Database (T-SQL)
-- ============================================================================

SET NOCOUNT ON;

-- Enable IDENTITY_INSERT for seeding with explicit IDs
-- ============================================================================
-- CUSTOMERS (55 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[customers] ON;

MERGE [dbo].[customers] AS target
USING (VALUES
    (1,  N'Alice',    N'Johnson',   N'alice.johnson@example.com',    N'+1-555-0101', N'Enterprise', N'North America', '2023-01-15T10:30:00'),
    (2,  N'Bob',      N'Smith',     N'bob.smith@example.com',        N'+1-555-0102', N'SMB',        N'North America', '2023-01-20T14:15:00'),
    (3,  N'Carlos',   N'Garcia',    N'carlos.garcia@example.com',    N'+1-555-0103', N'Enterprise', N'Latin America', '2023-02-01T09:00:00'),
    (4,  N'Diana',    N'Chen',      N'diana.chen@example.com',       N'+1-555-0104', N'Mid-Market', N'Asia Pacific',  '2023-02-10T11:45:00'),
    (5,  N'Erik',     N'Mueller',   N'erik.mueller@example.com',     N'+49-555-0105', N'Enterprise', N'Europe',       '2023-02-15T08:20:00'),
    (6,  N'Fatima',   N'Al-Hassan', N'fatima.alhassan@example.com',  N'+971-555-0106', N'SMB',       N'Middle East',  '2023-02-20T16:00:00'),
    (7,  N'George',   N'Williams',  N'george.williams@example.com',  N'+1-555-0107', N'Mid-Market', N'North America', '2023-03-01T13:30:00'),
    (8,  N'Hana',     N'Tanaka',    N'hana.tanaka@example.com',      N'+81-555-0108', N'Enterprise', N'Asia Pacific', '2023-03-05T07:15:00'),
    (9,  N'Ivan',     N'Petrov',    N'ivan.petrov@example.com',      N'+7-555-0109', N'SMB',        N'Europe',        '2023-03-10T10:00:00'),
    (10, N'Julia',    N'Santos',    N'julia.santos@example.com',     N'+55-555-0110', N'Mid-Market', N'Latin America', '2023-03-15T12:45:00'),
    (11, N'Kevin',    N'O''Brien',  N'kevin.obrien@example.com',     N'+353-555-0111', N'SMB',       N'Europe',       '2023-03-20T09:30:00'),
    (12, N'Lina',     N'Park',      N'lina.park@example.com',        N'+82-555-0112', N'Enterprise', N'Asia Pacific', '2023-03-25T15:00:00'),
    (13, N'Marcus',   N'Brown',     N'marcus.brown@example.com',     N'+1-555-0113', N'Mid-Market', N'North America', '2023-04-01T08:45:00'),
    (14, N'Nina',     N'Johansson', N'nina.johansson@example.com',   N'+46-555-0114', N'Enterprise', N'Europe',       '2023-04-05T14:20:00'),
    (15, N'Oscar',    N'Rivera',    N'oscar.rivera@example.com',     N'+52-555-0115', N'SMB',        N'Latin America', '2023-04-10T11:10:00'),
    (16, N'Priya',    N'Patel',     N'priya.patel@example.com',      N'+91-555-0116', N'Enterprise', N'Asia Pacific', '2023-04-15T06:30:00'),
    (17, N'Quinn',    N'Taylor',    N'quinn.taylor@example.com',     N'+1-555-0117', N'Mid-Market', N'North America', '2023-04-20T16:45:00'),
    (18, N'Ravi',     N'Kumar',     N'ravi.kumar@example.com',       N'+91-555-0118', N'SMB',        N'Asia Pacific', '2023-04-25T10:15:00'),
    (19, N'Sofia',    N'Rossi',     N'sofia.rossi@example.com',      N'+39-555-0119', N'Enterprise', N'Europe',       '2023-05-01T13:00:00'),
    (20, N'Thomas',   N'Anderson',  N'thomas.anderson@example.com',  N'+1-555-0120', N'Mid-Market', N'North America', '2023-05-05T09:20:00'),
    (21, N'Uma',      N'Krishnan',  N'uma.krishnan@example.com',     N'+91-555-0121', N'Enterprise', N'Asia Pacific', '2023-05-10T07:00:00'),
    (22, N'Victor',   N'Lopez',     N'victor.lopez@example.com',     N'+34-555-0122', N'SMB',        N'Europe',       '2023-05-15T15:30:00'),
    (23, N'Wendy',    N'Zhang',     N'wendy.zhang@example.com',      N'+86-555-0123', N'Mid-Market', N'Asia Pacific', '2023-05-20T11:45:00'),
    (24, N'Xavier',   N'Dubois',    N'xavier.dubois@example.com',    N'+33-555-0124', N'Enterprise', N'Europe',       '2023-05-25T08:10:00'),
    (25, N'Yuki',     N'Sato',      N'yuki.sato@example.com',        N'+81-555-0125', N'SMB',        N'Asia Pacific', '2023-06-01T14:00:00'),
    (26, N'Zara',     N'Thompson',  N'zara.thompson@example.com',    N'+44-555-0126', N'Mid-Market', N'Europe',       '2023-06-05T10:30:00'),
    (27, N'Adam',     N'Wilson',    N'adam.wilson@example.com',       N'+1-555-0127', N'Enterprise', N'North America', '2023-06-10T12:00:00'),
    (28, N'Bianca',   N'Ferrari',   N'bianca.ferrari@example.com',   N'+39-555-0128', N'SMB',        N'Europe',       '2023-06-15T09:45:00'),
    (29, N'Chris',    N'Lee',       N'chris.lee@example.com',        N'+1-555-0129', N'Mid-Market', N'North America', '2023-06-20T16:15:00'),
    (30, N'Daria',    N'Volkov',    N'daria.volkov@example.com',     N'+7-555-0130', N'Enterprise', N'Europe',        '2023-06-25T07:30:00'),
    (31, N'Ethan',    N'Davis',     N'ethan.davis@example.com',      N'+1-555-0131', N'SMB',        N'North America', '2023-07-01T13:20:00'),
    (32, N'Fiona',    N'MacLeod',   N'fiona.macleod@example.com',    N'+44-555-0132', N'Mid-Market', N'Europe',       '2023-07-05T11:00:00'),
    (33, N'Gustavo',  N'Herrera',   N'gustavo.herrera@example.com',  N'+57-555-0133', N'Enterprise', N'Latin America', '2023-07-10T08:40:00'),
    (34, N'Helen',    N'Nguyen',    N'helen.nguyen@example.com',     N'+84-555-0134', N'SMB',        N'Asia Pacific', '2023-07-15T15:50:00'),
    (35, N'Igor',     N'Novak',     N'igor.novak@example.com',       N'+385-555-0135', N'Mid-Market', N'Europe',      '2023-07-20T10:25:00'),
    (36, N'Jasmine',  N'Carter',    N'jasmine.carter@example.com',   N'+1-555-0136', N'Enterprise', N'North America', '2023-07-25T14:35:00'),
    (37, N'Kenji',    N'Yamamoto',  N'kenji.yamamoto@example.com',   N'+81-555-0137', N'SMB',        N'Asia Pacific', '2023-08-01T06:50:00'),
    (38, N'Laura',    N'Martinez',  N'laura.martinez@example.com',   N'+34-555-0138', N'Mid-Market', N'Europe',       '2023-08-05T12:10:00'),
    (39, N'Mohammed', N'Ali',       N'mohammed.ali@example.com',     N'+20-555-0139', N'Enterprise', N'Middle East',  '2023-08-10T09:00:00'),
    (40, N'Nora',     N'Eriksen',   N'nora.eriksen@example.com',     N'+47-555-0140', N'SMB',        N'Europe',       '2023-08-15T16:20:00'),
    (41, N'Oliver',   N'King',      N'oliver.king@example.com',      N'+44-555-0141', N'Mid-Market', N'Europe',       '2023-08-20T11:30:00'),
    (42, N'Patricia', N'Souza',     N'patricia.souza@example.com',   N'+55-555-0142', N'Enterprise', N'Latin America', '2023-08-25T08:15:00'),
    (43, N'Rafael',   N'Mendez',    N'rafael.mendez@example.com',    N'+52-555-0143', N'SMB',        N'Latin America', '2023-09-01T13:45:00'),
    (44, N'Sarah',    N'White',     N'sarah.white@example.com',      N'+1-555-0144', N'Mid-Market', N'North America', '2023-09-05T10:00:00'),
    (45, N'Takeshi',  N'Nakamura',  N'takeshi.nakamura@example.com', N'+81-555-0145', N'Enterprise', N'Asia Pacific', '2023-09-10T07:25:00'),
    (46, N'Ursula',   N'Schmidt',   N'ursula.schmidt@example.com',   N'+49-555-0146', N'SMB',        N'Europe',       '2023-09-15T14:40:00'),
    (47, N'Vincent',  N'Moreau',    N'vincent.moreau@example.com',   N'+33-555-0147', N'Mid-Market', N'Europe',       '2023-09-20T09:55:00'),
    (48, N'Wendy',    N'Clark',     N'wendy.clark@example.com',      N'+1-555-0148', N'Enterprise', N'North America', '2023-09-25T15:10:00'),
    (49, N'Xin',      N'Wang',      N'xin.wang@example.com',         N'+86-555-0149', N'SMB',        N'Asia Pacific', '2023-10-01T11:20:00'),
    (50, N'Yolanda',  N'Reyes',     N'yolanda.reyes@example.com',    N'+52-555-0150', N'Mid-Market', N'Latin America', '2023-10-05T08:35:00'),
    (51, N'Zach',     N'Miller',    N'zach.miller@example.com',      N'+1-555-0151', N'Enterprise', N'North America', '2023-10-10T13:00:00'),
    (52, N'Amelia',   N'Hughes',    N'amelia.hughes@example.com',    N'+44-555-0152', N'SMB',        N'Europe',       '2023-10-15T10:45:00'),
    (53, N'Bruno',    N'Costa',     N'bruno.costa@example.com',      N'+55-555-0153', N'Mid-Market', N'Latin America', '2023-10-20T07:50:00'),
    (54, N'Clara',    N'Fischer',   N'clara.fischer@example.com',    N'+49-555-0154', N'Enterprise', N'Europe',       '2023-10-25T14:05:00'),
    (55, N'Daniel',   N'Kim',       N'daniel.kim@example.com',       N'+82-555-0155', N'SMB',        N'Asia Pacific', '2023-11-01T09:15:00')
) AS source (customer_id, first_name, last_name, email, phone, segment, region, created_at)
ON target.customer_id = source.customer_id
WHEN MATCHED THEN
    UPDATE SET
        first_name = source.first_name,
        last_name = source.last_name,
        email = source.email,
        phone = source.phone,
        segment = source.segment,
        region = source.region,
        created_at = source.created_at
WHEN NOT MATCHED THEN
    INSERT (customer_id, first_name, last_name, email, phone, segment, region, created_at)
    VALUES (source.customer_id, source.first_name, source.last_name, source.email, source.phone, source.segment, source.region, source.created_at);

SET IDENTITY_INSERT [dbo].[customers] OFF;
GO

-- ============================================================================
-- PRODUCTS (55 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[products] ON;

MERGE [dbo].[products] AS target
USING (VALUES
    (1,  N'Wireless Mouse',           N'Electronics',    N'Peripherals',      N'LogiTech',    15.00,  29.99),
    (2,  N'Mechanical Keyboard',      N'Electronics',    N'Peripherals',      N'KeyMaster',   45.00,  89.99),
    (3,  N'USB-C Hub 7-Port',         N'Electronics',    N'Accessories',      N'HubMax',      22.00,  49.99),
    (4,  N'27" 4K Monitor',           N'Electronics',    N'Displays',         N'ViewPro',     180.00, 399.99),
    (5,  N'Noise Cancelling Headset', N'Electronics',    N'Audio',            N'SoundWave',   65.00,  149.99),
    (6,  N'Standing Desk',            N'Furniture',      N'Desks',            N'ErgoLift',    250.00, 549.99),
    (7,  N'Ergonomic Chair',          N'Furniture',      N'Chairs',           N'ComfortZone', 180.00, 399.99),
    (8,  N'Desk Lamp LED',            N'Furniture',      N'Lighting',         N'BrightPath',  18.00,  39.99),
    (9,  N'Monitor Arm',              N'Furniture',      N'Accessories',      N'FlexMount',   35.00,  79.99),
    (10, N'Cable Management Kit',     N'Furniture',      N'Accessories',      N'TidyDesk',    8.00,   19.99),
    (11, N'Laptop Stand Aluminum',    N'Electronics',    N'Accessories',      N'AluStand',    20.00,  44.99),
    (12, N'Webcam 1080p',             N'Electronics',    N'Peripherals',      N'ClearView',   25.00,  59.99),
    (13, N'Portable SSD 1TB',         N'Electronics',    N'Storage',          N'SpeedDisk',   55.00,  119.99),
    (14, N'Wireless Charger Pad',     N'Electronics',    N'Power',            N'ChargeFast',  12.00,  29.99),
    (15, N'USB Microphone',           N'Electronics',    N'Audio',            N'VoicePro',    40.00,  89.99),
    (16, N'Whiteboard 48x36',         N'Office Supply',  N'Boards',           N'WriteRight',  25.00,  59.99),
    (17, N'Notebook A5 Pack of 3',    N'Office Supply',  N'Paper',            N'PaperMate',   4.00,   9.99),
    (18, N'Pen Set Premium',          N'Office Supply',  N'Writing',          N'InkFlow',     8.00,   19.99),
    (19, N'Sticky Notes Multicolor',  N'Office Supply',  N'Paper',            N'StickyBrand', 2.50,   5.99),
    (20, N'Document Shredder',        N'Office Supply',  N'Equipment',        N'ShredSafe',   60.00,  129.99),
    (21, N'Filing Cabinet 3-Drawer',  N'Furniture',      N'Storage',          N'OrgMax',      90.00,  199.99),
    (22, N'Bookshelf Modern',         N'Furniture',      N'Storage',          N'ShelfStyle',  75.00,  169.99),
    (23, N'Printer All-in-One',       N'Electronics',    N'Printers',         N'PrintPro',    120.00, 249.99),
    (24, N'Ink Cartridge Black',      N'Office Supply',  N'Printer Supplies', N'PrintPro',    15.00,  34.99),
    (25, N'Ink Cartridge Color',      N'Office Supply',  N'Printer Supplies', N'PrintPro',    20.00,  44.99),
    (26, N'Wireless Presenter',       N'Electronics',    N'Peripherals',      N'ClickPoint',  18.00,  39.99),
    (27, N'Surge Protector 8-Outlet', N'Electronics',    N'Power',            N'SafeVolt',    15.00,  34.99),
    (28, N'UPS Battery Backup',       N'Electronics',    N'Power',            N'PowerGuard',  80.00,  179.99),
    (29, N'Desk Organizer Set',       N'Office Supply',  N'Organization',     N'TidyDesk',    12.00,  27.99),
    (30, N'Anti-Fatigue Mat',         N'Furniture',      N'Accessories',      N'ComfortZone', 25.00,  54.99),
    (31, N'Bluetooth Speaker',        N'Electronics',    N'Audio',            N'SoundWave',   30.00,  69.99),
    (32, N'Screen Privacy Filter',    N'Electronics',    N'Accessories',      N'SecureView',  20.00,  44.99),
    (33, N'Ethernet Cable 10ft',      N'Electronics',    N'Networking',       N'NetLink',     3.00,   8.99),
    (34, N'Wi-Fi Range Extender',     N'Electronics',    N'Networking',       N'NetLink',     25.00,  54.99),
    (35, N'Mouse Pad XL',             N'Electronics',    N'Peripherals',      N'GlidePad',    8.00,   19.99),
    (36, N'Wrist Rest Keyboard',      N'Electronics',    N'Accessories',      N'ComfortZone', 10.00,  24.99),
    (37, N'Paper Clips Box 1000',     N'Office Supply',  N'Fasteners',        N'ClipIt',      2.00,   4.99),
    (38, N'Stapler Heavy Duty',       N'Office Supply',  N'Fasteners',        N'StaplePro',   12.00,  24.99),
    (39, N'Label Maker',              N'Office Supply',  N'Equipment',        N'TagIt',       20.00,  44.99),
    (40, N'Tape Dispenser',           N'Office Supply',  N'Equipment',        N'StickFast',   5.00,   12.99),
    (41, N'Conference Phone',         N'Electronics',    N'Audio',            N'VoicePro',    150.00, 329.99),
    (42, N'Projector Portable',       N'Electronics',    N'Displays',         N'ViewPro',     200.00, 449.99),
    (43, N'Projector Screen 100"',    N'Electronics',    N'Displays',         N'ViewPro',     60.00,  129.99),
    (44, N'Power Strip USB',          N'Electronics',    N'Power',            N'SafeVolt',    10.00,  22.99),
    (45, N'Desk Calendar 2024',       N'Office Supply',  N'Paper',            N'PlanAhead',   5.00,   12.99),
    (46, N'Planner Weekly',           N'Office Supply',  N'Paper',            N'PlanAhead',   8.00,   17.99),
    (47, N'Highlighter Set 6-Pack',   N'Office Supply',  N'Writing',          N'InkFlow',     3.00,   7.99),
    (48, N'Dry Erase Markers 8-Pack', N'Office Supply',  N'Writing',          N'WriteRight',  4.00,   9.99),
    (49, N'Laptop Backpack',          N'Office Supply',  N'Bags',             N'CarryAll',    30.00,  69.99),
    (50, N'Desk Fan USB',             N'Electronics',    N'Accessories',      N'CoolBreeze',  8.00,   18.99),
    (51, N'Blue Light Glasses',       N'Office Supply',  N'Ergonomics',       N'EyeCare',     12.00,  29.99),
    (52, N'Footrest Adjustable',      N'Furniture',      N'Ergonomics',       N'ComfortZone', 20.00,  44.99),
    (53, N'Keyboard Cover',           N'Electronics',    N'Accessories',      N'KeyMaster',   5.00,   12.99),
    (54, N'Webcam Ring Light',        N'Electronics',    N'Lighting',         N'BrightPath',  15.00,  34.99),
    (55, N'Document Scanner',         N'Electronics',    N'Peripherals',      N'ScanFast',    85.00,  189.99)
) AS source (product_id, name, category, sub_category, brand, cost_price, list_price)
ON target.product_id = source.product_id
WHEN MATCHED THEN
    UPDATE SET
        name = source.name,
        category = source.category,
        sub_category = source.sub_category,
        brand = source.brand,
        cost_price = source.cost_price,
        list_price = source.list_price
WHEN NOT MATCHED THEN
    INSERT (product_id, name, category, sub_category, brand, cost_price, list_price)
    VALUES (source.product_id, source.name, source.category, source.sub_category, source.brand, source.cost_price, source.list_price);

SET IDENTITY_INSERT [dbo].[products] OFF;
GO

-- ============================================================================
-- ORDERS (60 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[orders] ON;

MERGE [dbo].[orders] AS target
USING (VALUES
    (1,  1,  '2023-03-01T09:15:00', N'completed',  189.97,  0.00,   N'online'),
    (2,  2,  '2023-03-05T14:30:00', N'completed',  89.99,   5.00,   N'online'),
    (3,  3,  '2023-03-10T11:00:00', N'completed',  549.99,  25.00,  N'phone'),
    (4,  4,  '2023-03-15T16:45:00', N'shipped',    449.98,  0.00,   N'online'),
    (5,  5,  '2023-03-20T08:20:00', N'completed',  119.99,  10.00,  N'in-store'),
    (6,  1,  '2023-04-01T10:00:00', N'completed',  79.98,   0.00,   N'online'),
    (7,  6,  '2023-04-05T13:30:00', N'completed',  399.99,  20.00,  N'phone'),
    (8,  7,  '2023-04-10T09:45:00', N'cancelled',  29.99,   0.00,   N'online'),
    (9,  8,  '2023-04-15T15:10:00', N'completed',  849.97,  50.00,  N'online'),
    (10, 9,  '2023-04-20T11:25:00', N'completed',  59.99,   0.00,   N'in-store'),
    (11, 10, '2023-05-01T08:00:00', N'completed',  249.99,  15.00,  N'online'),
    (12, 11, '2023-05-05T14:15:00', N'completed',  44.99,   0.00,   N'online'),
    (13, 12, '2023-05-10T10:30:00', N'shipped',    699.98,  35.00,  N'phone'),
    (14, 13, '2023-05-15T16:00:00', N'completed',  169.99,  0.00,   N'online'),
    (15, 14, '2023-05-20T09:40:00', N'completed',  89.99,   5.00,   N'in-store'),
    (16, 15, '2023-06-01T12:00:00', N'completed',  329.99,  0.00,   N'online'),
    (17, 16, '2023-06-05T07:30:00', N'completed',  549.99,  30.00,  N'online'),
    (18, 17, '2023-06-10T15:45:00', N'pending',    199.99,  0.00,   N'phone'),
    (19, 18, '2023-06-15T10:20:00', N'completed',  69.99,   0.00,   N'online'),
    (20, 19, '2023-06-20T13:55:00', N'completed',  399.99,  20.00,  N'in-store'),
    (21, 20, '2023-07-01T08:10:00', N'completed',  129.99,  0.00,   N'online'),
    (22, 21, '2023-07-05T14:30:00', N'completed',  449.99,  25.00,  N'online'),
    (23, 22, '2023-07-10T11:00:00', N'shipped',    59.99,   0.00,   N'phone'),
    (24, 23, '2023-07-15T16:20:00', N'completed',  179.99,  10.00,  N'online'),
    (25, 24, '2023-07-20T09:00:00', N'completed',  89.99,   0.00,   N'in-store'),
    (26, 25, '2023-08-01T12:30:00', N'completed',  249.99,  15.00,  N'online'),
    (27, 26, '2023-08-05T07:45:00', N'cancelled',  34.99,   0.00,   N'online'),
    (28, 27, '2023-08-10T15:15:00', N'completed',  599.98,  30.00,  N'phone'),
    (29, 28, '2023-08-15T10:40:00', N'completed',  44.99,   0.00,   N'online'),
    (30, 29, '2023-08-20T13:00:00', N'completed',  149.99,  0.00,   N'in-store'),
    (31, 30, '2023-09-01T08:30:00', N'completed',  329.99,  20.00,  N'online'),
    (32, 31, '2023-09-05T14:50:00', N'completed',  89.99,   5.00,   N'online'),
    (33, 32, '2023-09-10T11:10:00', N'shipped',    199.99,  0.00,   N'phone'),
    (34, 33, '2023-09-15T16:30:00', N'completed',  549.99,  25.00,  N'online'),
    (35, 34, '2023-09-20T09:20:00', N'completed',  69.99,   0.00,   N'in-store'),
    (36, 35, '2023-10-01T12:45:00', N'completed',  119.99,  10.00,  N'online'),
    (37, 36, '2023-10-05T07:55:00', N'completed',  449.99,  0.00,   N'online'),
    (38, 37, '2023-10-10T15:20:00', N'pending',    24.99,   0.00,   N'phone'),
    (39, 38, '2023-10-15T10:00:00', N'completed',  179.99,  10.00,  N'online'),
    (40, 39, '2023-10-20T13:30:00', N'completed',  399.99,  20.00,  N'in-store'),
    (41, 40, '2023-11-01T08:15:00', N'completed',  54.99,   0.00,   N'online'),
    (42, 41, '2023-11-05T14:40:00', N'completed',  329.99,  15.00,  N'online'),
    (43, 42, '2023-11-10T11:20:00', N'shipped',    89.99,   5.00,   N'phone'),
    (44, 43, '2023-11-15T16:50:00', N'completed',  249.99,  0.00,   N'online'),
    (45, 44, '2023-11-20T09:30:00', N'completed',  129.99,  10.00,  N'in-store'),
    (46, 45, '2023-12-01T12:00:00', N'completed',  599.98,  30.00,  N'online'),
    (47, 46, '2023-12-05T07:15:00', N'completed',  44.99,   0.00,   N'online'),
    (48, 47, '2023-12-10T15:30:00', N'pending',    179.99,  0.00,   N'phone'),
    (49, 48, '2023-12-15T10:45:00', N'completed',  399.99,  20.00,  N'online'),
    (50, 49, '2023-12-20T13:10:00', N'completed',  69.99,   0.00,   N'in-store'),
    (51, 50, '2024-01-02T08:00:00', N'completed',  189.99,  0.00,   N'online'),
    (52, 51, '2024-01-05T14:20:00', N'completed',  249.99,  15.00,  N'online'),
    (53, 52, '2024-01-10T11:30:00', N'shipped',    89.99,   5.00,   N'phone'),
    (54, 53, '2024-01-15T16:00:00', N'completed',  449.99,  25.00,  N'online'),
    (55, 54, '2024-01-20T09:45:00', N'completed',  129.99,  0.00,   N'in-store'),
    (56, 55, '2024-01-25T12:15:00', N'completed',  59.99,   0.00,   N'online'),
    (57, 1,  '2024-02-01T07:30:00', N'completed',  329.99,  20.00,  N'online'),
    (58, 5,  '2024-02-05T15:00:00', N'pending',    549.99,  25.00,  N'phone'),
    (59, 10, '2024-02-10T10:20:00', N'completed',  89.99,   0.00,   N'online'),
    (60, 15, '2024-02-15T13:45:00', N'completed',  199.99,  10.00,  N'in-store')
) AS source (order_id, customer_id, order_date, status, total_amount, discount, channel)
ON target.order_id = source.order_id
WHEN MATCHED THEN
    UPDATE SET
        customer_id = source.customer_id,
        order_date = source.order_date,
        status = source.status,
        total_amount = source.total_amount,
        discount = source.discount,
        channel = source.channel
WHEN NOT MATCHED THEN
    INSERT (order_id, customer_id, order_date, status, total_amount, discount, channel)
    VALUES (source.order_id, source.customer_id, source.order_date, source.status, source.total_amount, source.discount, source.channel);

SET IDENTITY_INSERT [dbo].[orders] OFF;
GO

-- ============================================================================
-- ORDER_ITEMS (65 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[order_items] ON;

MERGE [dbo].[order_items] AS target
USING (VALUES
    (1,  1,  1,  2, 29.99,  59.98),
    (2,  1,  5,  1, 149.99, 149.99),
    (3,  2,  2,  1, 89.99,  89.99),
    (4,  3,  6,  1, 549.99, 549.99),
    (5,  4,  4,  1, 399.99, 399.99),
    (6,  4,  11, 1, 44.99,  44.99),
    (7,  5,  13, 1, 119.99, 119.99),
    (8,  6,  9,  1, 79.99,  79.99),
    (9,  7,  7,  1, 399.99, 399.99),
    (10, 8,  1,  1, 29.99,  29.99),
    (11, 9,  4,  1, 399.99, 399.99),
    (12, 9,  5,  1, 149.99, 149.99),
    (13, 9,  3,  1, 49.99,  49.99),
    (14, 10, 12, 1, 59.99,  59.99),
    (15, 11, 23, 1, 249.99, 249.99),
    (16, 12, 11, 1, 44.99,  44.99),
    (17, 13, 4,  1, 399.99, 399.99),
    (18, 13, 9,  1, 79.99,  79.99),
    (19, 14, 22, 1, 169.99, 169.99),
    (20, 15, 2,  1, 89.99,  89.99),
    (21, 16, 41, 1, 329.99, 329.99),
    (22, 17, 6,  1, 549.99, 549.99),
    (23, 18, 21, 1, 199.99, 199.99),
    (24, 19, 31, 1, 69.99,  69.99),
    (25, 20, 7,  1, 399.99, 399.99),
    (26, 21, 13, 1, 119.99, 119.99),
    (27, 22, 42, 1, 449.99, 449.99),
    (28, 23, 10, 1, 19.99,  19.99),
    (29, 23, 35, 2, 19.99,  39.98),
    (30, 24, 28, 1, 179.99, 179.99),
    (31, 25, 2,  1, 89.99,  89.99),
    (32, 26, 23, 1, 249.99, 249.99),
    (33, 27, 27, 1, 34.99,  34.99),
    (34, 28, 6,  1, 549.99, 549.99),
    (35, 28, 8,  1, 39.99,  39.99),
    (36, 29, 11, 1, 44.99,  44.99),
    (37, 30, 5,  1, 149.99, 149.99),
    (38, 31, 41, 1, 329.99, 329.99),
    (39, 32, 2,  1, 89.99,  89.99),
    (40, 33, 21, 1, 199.99, 199.99),
    (41, 34, 6,  1, 549.99, 549.99),
    (42, 35, 31, 1, 69.99,  69.99),
    (43, 36, 13, 1, 119.99, 119.99),
    (44, 37, 42, 1, 449.99, 449.99),
    (45, 38, 19, 5, 5.99,   29.95),
    (46, 39, 28, 1, 179.99, 179.99),
    (47, 40, 7,  1, 399.99, 399.99),
    (48, 41, 30, 1, 54.99,  54.99),
    (49, 42, 41, 1, 329.99, 329.99),
    (50, 43, 2,  1, 89.99,  89.99),
    (51, 44, 23, 1, 249.99, 249.99),
    (52, 45, 5,  1, 149.99, 149.99),
    (53, 46, 6,  1, 549.99, 549.99),
    (54, 46, 8,  1, 39.99,  39.99),
    (55, 47, 11, 1, 44.99,  44.99),
    (56, 48, 28, 1, 179.99, 179.99),
    (57, 49, 7,  1, 399.99, 399.99),
    (58, 50, 31, 1, 69.99,  69.99),
    (59, 51, 15, 1, 89.99,  89.99),
    (60, 51, 12, 1, 59.99,  59.99),
    (61, 52, 23, 1, 249.99, 249.99),
    (62, 53, 2,  1, 89.99,  89.99),
    (63, 54, 42, 1, 449.99, 449.99),
    (64, 55, 5,  1, 149.99, 149.99),
    (65, 56, 12, 1, 59.99,  59.99)
) AS source (item_id, order_id, product_id, quantity, unit_price, line_total)
ON target.item_id = source.item_id
WHEN MATCHED THEN
    UPDATE SET
        order_id = source.order_id,
        product_id = source.product_id,
        quantity = source.quantity,
        unit_price = source.unit_price,
        line_total = source.line_total
WHEN NOT MATCHED THEN
    INSERT (item_id, order_id, product_id, quantity, unit_price, line_total)
    VALUES (source.item_id, source.order_id, source.product_id, source.quantity, source.unit_price, source.line_total);

SET IDENTITY_INSERT [dbo].[order_items] OFF;
GO

-- ============================================================================
-- CAMPAIGNS (52 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[campaigns] ON;

MERGE [dbo].[campaigns] AS target
USING (VALUES
    (1,  N'Spring Electronics Sale',      N'email',         '2023-03-01', '2023-03-31', 15000.00, 12500.00),
    (2,  N'New Customer Welcome',         N'email',         '2023-01-01', '2023-12-31', 5000.00,  4800.00),
    (3,  N'Social Media Brand Awareness', N'social',        '2023-02-01', '2023-04-30', 20000.00, 18500.00),
    (4,  N'Google Ads - Electronics',     N'paid_search',   '2023-03-01', '2023-05-31', 30000.00, 28000.00),
    (5,  N'Summer Furniture Promo',       N'email',         '2023-06-01', '2023-08-31', 12000.00, 11000.00),
    (6,  N'Back to Office Campaign',      N'display',       '2023-08-15', '2023-09-30', 25000.00, 22000.00),
    (7,  N'Holiday Gift Guide',           N'email',         '2023-11-01', '2023-12-25', 18000.00, 17500.00),
    (8,  N'LinkedIn B2B Outreach',        N'social',        '2023-04-01', '2023-06-30', 10000.00, 9200.00),
    (9,  N'YouTube Product Reviews',      N'video',         '2023-05-01', '2023-07-31', 35000.00, 32000.00),
    (10, N'Referral Program Launch',      N'referral',      '2023-03-15', '2023-09-15', 8000.00,  7500.00),
    (11, N'Flash Sale Weekend',           N'email',         '2023-07-14', '2023-07-16', 3000.00,  2900.00),
    (12, N'Instagram Stories Ads',        N'social',        '2023-06-01', '2023-08-31', 15000.00, 14200.00),
    (13, N'Retargeting - Cart Abandon',   N'display',       '2023-01-01', '2023-12-31', 20000.00, 19000.00),
    (14, N'Podcast Sponsorship',          N'audio',         '2023-09-01', '2023-11-30', 12000.00, 12000.00),
    (15, N'Black Friday Deals',           N'email',         '2023-11-20', '2023-11-27', 25000.00, 24500.00),
    (16, N'Cyber Monday Special',         N'paid_search',   '2023-11-27', '2023-11-27', 15000.00, 14800.00),
    (17, N'New Year Clearance',           N'email',         '2024-01-01', '2024-01-15', 8000.00,  6500.00),
    (18, N'Valentine Tech Gifts',         N'social',        '2024-02-01', '2024-02-14', 10000.00, 8500.00),
    (19, N'TikTok Product Showcase',      N'social',        '2023-07-01', '2023-09-30', 22000.00, 20000.00),
    (20, N'Email Win-Back Campaign',      N'email',         '2023-10-01', '2023-10-31', 4000.00,  3800.00),
    (21, N'Google Shopping Ads',          N'paid_search',   '2023-01-01', '2023-12-31', 40000.00, 38000.00),
    (22, N'Affiliate Program',            N'affiliate',     '2023-04-01', '2023-12-31', 15000.00, 13500.00),
    (23, N'SMS Flash Alerts',             N'sms',           '2023-08-01', '2023-10-31', 5000.00,  4500.00),
    (24, N'Content Marketing Blog',       N'content',       '2023-01-01', '2023-12-31', 6000.00,  5800.00),
    (25, N'Webinar Series',              N'content',       '2023-05-01', '2023-11-30', 8000.00,  7200.00),
    (26, N'Partner Co-Marketing',         N'partner',       '2023-06-01', '2023-08-31', 12000.00, 10000.00),
    (27, N'Product Launch - Monitors',    N'email',         '2023-04-01', '2023-04-30', 7000.00,  6800.00),
    (28, N'Customer Loyalty Rewards',     N'email',         '2023-01-01', '2023-12-31', 10000.00, 9500.00),
    (29, N'Trade Show Presence',          N'events',        '2023-09-15', '2023-09-18', 30000.00, 28000.00),
    (30, N'Bing Ads Experiment',          N'paid_search',   '2023-07-01', '2023-09-30', 5000.00,  4200.00),
    (31, N'Pinterest Visual Campaign',    N'social',        '2023-03-01', '2023-05-31', 8000.00,  7100.00),
    (32, N'SEO Content Push',             N'content',       '2023-02-01', '2023-12-31', 12000.00, 11000.00),
    (33, N'Employee Advocacy',            N'social',        '2023-01-01', '2023-12-31', 2000.00,  1800.00),
    (34, N'Direct Mail Premium',          N'direct_mail',   '2023-10-01', '2023-11-30', 15000.00, 14000.00),
    (35, N'App Push Notifications',       N'push',          '2023-06-01', '2023-12-31', 3000.00,  2800.00),
    (36, N'Cross-Sell Furniture',         N'email',         '2023-09-01', '2023-10-31', 6000.00,  5500.00),
    (37, N'Upsell Premium Tier',          N'email',         '2023-08-01', '2023-09-30', 4000.00,  3700.00),
    (38, N'Brand Video Series',           N'video',         '2023-04-01', '2023-07-31', 40000.00, 37000.00),
    (39, N'Local Store Events',           N'events',        '2023-05-01', '2023-10-31', 10000.00, 9000.00),
    (40, N'Facebook Marketplace',         N'social',        '2023-03-01', '2023-12-31', 18000.00, 16500.00),
    (41, N'Reddit Community Ads',         N'social',        '2023-07-01', '2023-10-31', 6000.00,  5200.00),
    (42, N'Influencer Partnerships',      N'influencer',    '2023-05-01', '2023-08-31', 25000.00, 23000.00),
    (43, N'Comparison Shopping',          N'paid_search',   '2023-01-01', '2023-12-31', 15000.00, 14000.00),
    (44, N'Abandoned Browse Email',       N'email',         '2023-04-01', '2023-12-31', 3000.00,  2800.00),
    (45, N'Seasonal Desk Accessories',    N'email',         '2023-10-01', '2023-11-30', 5000.00,  4600.00),
    (46, N'Tech Tuesday Newsletter',      N'email',         '2023-01-01', '2023-12-31', 2000.00,  1900.00),
    (47, N'Display Retargeting Global',   N'display',       '2023-01-01', '2023-12-31', 35000.00, 33000.00),
    (48, N'Students Back-to-School',      N'social',        '2023-08-01', '2023-09-15', 12000.00, 11000.00),
    (49, N'Corporate Bulk Discount',      N'direct_mail',   '2023-06-01', '2023-07-31', 7000.00,  6500.00),
    (50, N'Gamification Rewards',         N'push',          '2023-09-01', '2023-12-31', 4000.00,  3500.00),
    (51, N'Sustainability Campaign',      N'content',       '2023-10-01', '2023-12-31', 6000.00,  5000.00),
    (52, N'Q1 2024 Brand Refresh',        N'social',        '2024-01-01', '2024-03-31', 20000.00, 8000.00)
) AS source (campaign_id, name, channel, start_date, end_date, budget, spend)
ON target.campaign_id = source.campaign_id
WHEN MATCHED THEN
    UPDATE SET
        name = source.name,
        channel = source.channel,
        start_date = source.start_date,
        end_date = source.end_date,
        budget = source.budget,
        spend = source.spend
WHEN NOT MATCHED THEN
    INSERT (campaign_id, name, channel, start_date, end_date, budget, spend)
    VALUES (source.campaign_id, source.name, source.channel, source.start_date, source.end_date, source.budget, source.spend);

SET IDENTITY_INSERT [dbo].[campaigns] OFF;
GO

-- ============================================================================
-- CAMPAIGN_CONVERSIONS (55 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[campaign_conversions] ON;

MERGE [dbo].[campaign_conversions] AS target
USING (VALUES
    (1,  1,  1,  1,  '2023-03-01T09:20:00'),
    (2,  2,  2,  2,  '2023-03-05T14:35:00'),
    (3,  4,  3,  3,  '2023-03-10T11:05:00'),
    (4,  1,  4,  4,  '2023-03-15T16:50:00'),
    (5,  3,  5,  5,  '2023-03-20T08:25:00'),
    (6,  2,  6,  7,  '2023-04-05T13:35:00'),
    (7,  4,  7,  NULL, '2023-04-08T10:00:00'),
    (8,  1,  8,  9,  '2023-04-15T15:15:00'),
    (9,  10, 9,  10, '2023-04-20T11:30:00'),
    (10, 5,  10, 11, '2023-05-01T08:05:00'),
    (11, 2,  11, 12, '2023-05-05T14:20:00'),
    (12, 8,  12, 13, '2023-05-10T10:35:00'),
    (13, 4,  13, 14, '2023-05-15T16:05:00'),
    (14, 3,  14, 15, '2023-05-20T09:45:00'),
    (15, 5,  15, 16, '2023-06-01T12:05:00'),
    (16, 9,  16, 17, '2023-06-05T07:35:00'),
    (17, 12, 17, NULL, '2023-06-08T12:00:00'),
    (18, 5,  18, 19, '2023-06-15T10:25:00'),
    (19, 8,  19, 20, '2023-06-20T14:00:00'),
    (20, 10, 20, 21, '2023-07-01T08:15:00'),
    (21, 9,  21, 22, '2023-07-05T14:35:00'),
    (22, 13, 22, 23, '2023-07-10T11:05:00'),
    (23, 11, 23, 24, '2023-07-15T16:25:00'),
    (24, 12, 24, 25, '2023-07-20T09:05:00'),
    (25, 5,  25, 26, '2023-08-01T12:35:00'),
    (26, 6,  26, NULL, '2023-08-03T09:00:00'),
    (27, 6,  27, 28, '2023-08-10T15:20:00'),
    (28, 13, 28, 29, '2023-08-15T10:45:00'),
    (29, 14, 29, 30, '2023-08-20T13:05:00'),
    (30, 6,  30, 31, '2023-09-01T08:35:00'),
    (31, 23, 31, 32, '2023-09-05T14:55:00'),
    (32, 6,  32, 33, '2023-09-10T11:15:00'),
    (33, 14, 33, 34, '2023-09-15T16:35:00'),
    (34, 19, 34, 35, '2023-09-20T09:25:00'),
    (35, 20, 35, 36, '2023-10-01T12:50:00'),
    (36, 7,  36, 37, '2023-10-05T08:00:00'),
    (37, 21, 37, NULL, '2023-10-08T14:00:00'),
    (38, 15, 38, 39, '2023-10-15T10:05:00'),
    (39, 13, 39, 40, '2023-10-20T13:35:00'),
    (40, 7,  40, 41, '2023-11-01T08:20:00'),
    (41, 7,  41, 42, '2023-11-05T14:45:00'),
    (42, 15, 42, 43, '2023-11-10T11:25:00'),
    (43, 15, 43, 44, '2023-11-15T16:55:00'),
    (44, 7,  44, 45, '2023-11-20T09:35:00'),
    (45, 16, 45, 46, '2023-12-01T12:05:00'),
    (46, 7,  46, 47, '2023-12-05T07:20:00'),
    (47, 28, 47, 48, '2023-12-10T15:35:00'),
    (48, 7,  48, 49, '2023-12-15T10:50:00'),
    (49, 17, 49, 50, '2023-12-20T13:15:00'),
    (50, 17, 50, 51, '2024-01-02T08:05:00'),
    (51, 17, 51, 52, '2024-01-05T14:25:00'),
    (52, 18, 52, 53, '2024-01-10T11:35:00'),
    (53, 18, 53, 54, '2024-01-15T16:05:00'),
    (54, 52, 54, 55, '2024-01-20T09:50:00'),
    (55, 52, 55, 56, '2024-01-25T12:20:00')
) AS source (conversion_id, campaign_id, customer_id, order_id, conversion_date)
ON target.conversion_id = source.conversion_id
WHEN MATCHED THEN
    UPDATE SET
        campaign_id = source.campaign_id,
        customer_id = source.customer_id,
        order_id = source.order_id,
        conversion_date = source.conversion_date
WHEN NOT MATCHED THEN
    INSERT (conversion_id, campaign_id, customer_id, order_id, conversion_date)
    VALUES (source.conversion_id, source.campaign_id, source.customer_id, source.order_id, source.conversion_date);

SET IDENTITY_INSERT [dbo].[campaign_conversions] OFF;
GO

-- ============================================================================
-- SUPPORT_TICKETS (55 rows)
-- ============================================================================
SET IDENTITY_INSERT [dbo].[support_tickets] ON;

MERGE [dbo].[support_tickets] AS target
USING (VALUES
    (1,  2,  2,  N'Shipping',        N'medium', N'resolved', '2023-03-06T10:00:00', '2023-03-07T14:30:00'),
    (2,  4,  4,  N'Product Quality', N'high',   N'resolved', '2023-03-16T09:00:00', '2023-03-18T11:00:00'),
    (3,  8,  8,  N'Billing',         N'low',    N'resolved', '2023-04-11T13:00:00', '2023-04-11T15:00:00'),
    (4,  1,  1,  N'Returns',         N'medium', N'resolved', '2023-03-05T08:30:00', '2023-03-08T16:00:00'),
    (5,  5,  5,  N'Shipping',        N'high',   N'resolved', '2023-03-22T11:15:00', '2023-03-23T09:00:00'),
    (6,  10, 11, N'Product Quality', N'medium', N'resolved', '2023-05-03T14:20:00', '2023-05-05T10:30:00'),
    (7,  12, 13, N'Technical',       N'high',   N'resolved', '2023-05-12T09:45:00', '2023-05-13T16:00:00'),
    (8,  15, 16, N'Billing',         N'low',    N'resolved', '2023-06-02T11:30:00', '2023-06-02T14:00:00'),
    (9,  17, 18, N'Returns',         N'medium', N'resolved', '2023-06-12T15:00:00', '2023-06-15T10:00:00'),
    (10, 20, 20, N'Shipping',        N'high',   N'resolved', '2023-06-22T08:00:00', '2023-06-23T12:00:00'),
    (11, 3,  3,  N'Account',         N'low',    N'resolved', '2023-03-12T10:30:00', '2023-03-12T16:00:00'),
    (12, 7,  NULL, N'General',       N'low',    N'resolved', '2023-04-08T14:00:00', '2023-04-09T09:00:00'),
    (13, 9,  10, N'Product Quality', N'medium', N'resolved', '2023-04-21T11:00:00', '2023-04-23T15:30:00'),
    (14, 14, 15, N'Technical',       N'high',   N'resolved', '2023-05-21T08:45:00', '2023-05-22T11:00:00'),
    (15, 16, 17, N'Shipping',        N'medium', N'resolved', '2023-06-06T13:20:00', '2023-06-08T10:00:00'),
    (16, 19, 20, N'Returns',         N'high',   N'resolved', '2023-06-21T09:30:00', '2023-06-24T14:00:00'),
    (17, 22, 23, N'Billing',         N'low',    N'resolved', '2023-07-11T15:00:00', '2023-07-11T17:00:00'),
    (18, 25, 26, N'Account',         N'medium', N'resolved', '2023-08-02T10:00:00', '2023-08-03T12:00:00'),
    (19, 27, 28, N'Technical',       N'high',   N'resolved', '2023-08-11T08:30:00', '2023-08-12T16:00:00'),
    (20, 30, 31, N'Shipping',        N'medium', N'resolved', '2023-09-02T14:15:00', '2023-09-04T10:00:00'),
    (21, 33, 34, N'Product Quality', N'high',   N'resolved', '2023-09-16T11:00:00', '2023-09-18T09:30:00'),
    (22, 36, 37, N'Returns',         N'medium', N'resolved', '2023-10-06T09:00:00', '2023-10-09T14:00:00'),
    (23, 39, 40, N'Billing',         N'low',    N'resolved', '2023-10-21T13:45:00', '2023-10-21T16:00:00'),
    (24, 42, 43, N'Technical',       N'high',   N'resolved', '2023-11-11T08:00:00', '2023-11-12T11:30:00'),
    (25, 45, 46, N'Shipping',        N'medium', N'resolved', '2023-12-02T15:30:00', '2023-12-04T10:00:00'),
    (26, 48, 49, N'Account',         N'low',    N'resolved', '2023-12-16T10:20:00', '2023-12-16T14:00:00'),
    (27, 51, 52, N'Product Quality', N'high',   N'resolved', '2024-01-06T09:00:00', '2024-01-08T12:00:00'),
    (28, 54, 55, N'Returns',         N'medium', N'resolved', '2024-01-21T14:00:00', '2024-01-23T10:00:00'),
    (29, 1,  6,  N'Shipping',        N'low',    N'resolved', '2023-04-03T11:00:00', '2023-04-03T15:30:00'),
    (30, 6,  7,  N'Billing',         N'medium', N'resolved', '2023-04-07T09:45:00', '2023-04-08T14:00:00'),
    (31, 11, 12, N'Technical',       N'high',   N'resolved', '2023-05-06T13:30:00', '2023-05-07T10:00:00'),
    (32, 13, 14, N'Product Quality', N'medium', N'resolved', '2023-05-16T08:00:00', '2023-05-18T12:30:00'),
    (33, 18, 19, N'Returns',         N'low',    N'resolved', '2023-06-16T14:45:00', '2023-06-17T09:00:00'),
    (34, 21, 22, N'Shipping',        N'high',   N'resolved', '2023-07-06T10:00:00', '2023-07-07T14:00:00'),
    (35, 23, 24, N'Account',         N'medium', N'resolved', '2023-07-16T15:30:00', '2023-07-18T10:00:00'),
    (36, 26, NULL, N'General',       N'low',    N'resolved', '2023-08-06T09:00:00', '2023-08-06T12:00:00'),
    (37, 28, 29, N'Technical',       N'high',   N'resolved', '2023-08-16T14:00:00', '2023-08-17T11:30:00'),
    (38, 31, 32, N'Billing',         N'medium', N'resolved', '2023-09-06T10:30:00', '2023-09-07T14:00:00'),
    (39, 34, 35, N'Product Quality', N'high',   N'resolved', '2023-09-21T08:15:00', '2023-09-22T16:00:00'),
    (40, 37, 38, N'Shipping',        N'low',    N'resolved', '2023-10-11T13:00:00', '2023-10-12T09:00:00'),
    (41, 40, 41, N'Returns',         N'medium', N'open',     '2023-11-02T09:30:00', NULL),
    (42, 43, 44, N'Technical',       N'high',   N'open',     '2023-11-16T14:20:00', NULL),
    (43, 46, 47, N'Billing',         N'low',    N'open',     '2023-12-06T10:00:00', NULL),
    (44, 49, 50, N'Shipping',        N'medium', N'open',     '2023-12-21T15:00:00', NULL),
    (45, 52, 53, N'Account',         N'high',   N'open',     '2024-01-11T08:30:00', NULL),
    (46, 55, 56, N'Product Quality', N'medium', N'open',     '2024-01-26T13:00:00', NULL),
    (47, 2,  57, N'Returns',         N'low',    N'open',     '2024-02-02T10:45:00', NULL),
    (48, 8,  9,  N'Technical',       N'high',   N'escalated', '2023-04-16T09:00:00', NULL),
    (49, 16, 17, N'Billing',         N'critical', N'escalated', '2023-06-07T14:30:00', NULL),
    (50, 24, 25, N'Product Quality', N'critical', N'escalated', '2023-07-21T11:00:00', NULL),
    (51, 32, 33, N'Shipping',        N'high',   N'escalated', '2023-09-11T08:00:00', NULL),
    (52, 41, 42, N'Technical',       N'critical', N'escalated', '2023-11-06T15:30:00', NULL),
    (53, 50, 51, N'Account',         N'high',   N'escalated', '2024-01-03T10:00:00', NULL),
    (54, 44, 45, N'General',         N'low',    N'resolved', '2023-11-21T13:00:00', '2023-11-21T16:30:00'),
    (55, 47, 48, N'Returns',         N'medium', N'resolved', '2023-12-11T09:15:00', '2023-12-13T14:00:00')
) AS source (ticket_id, customer_id, order_id, category, priority, status, created_at, resolved_at)
ON target.ticket_id = source.ticket_id
WHEN MATCHED THEN
    UPDATE SET
        customer_id = source.customer_id,
        order_id = source.order_id,
        category = source.category,
        priority = source.priority,
        status = source.status,
        created_at = source.created_at,
        resolved_at = source.resolved_at
WHEN NOT MATCHED THEN
    INSERT (ticket_id, customer_id, order_id, category, priority, status, created_at, resolved_at)
    VALUES (source.ticket_id, source.customer_id, source.order_id, source.category, source.priority, source.status, source.created_at, source.resolved_at);

SET IDENTITY_INSERT [dbo].[support_tickets] OFF;
GO

-- ============================================================================
-- Re-seed identity values to continue after our explicit IDs
-- ============================================================================
DBCC CHECKIDENT ('[dbo].[customers]', RESEED);
DBCC CHECKIDENT ('[dbo].[products]', RESEED);
DBCC CHECKIDENT ('[dbo].[orders]', RESEED);
DBCC CHECKIDENT ('[dbo].[order_items]', RESEED);
DBCC CHECKIDENT ('[dbo].[campaigns]', RESEED);
DBCC CHECKIDENT ('[dbo].[campaign_conversions]', RESEED);
DBCC CHECKIDENT ('[dbo].[support_tickets]', RESEED);
GO

SET NOCOUNT OFF;
PRINT 'Seed data inserted successfully.';
GO
