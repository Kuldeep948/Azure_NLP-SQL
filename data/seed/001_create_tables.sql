-- ============================================================================
-- 001_create_tables.sql
-- Creates all 7 business tables for the NLP-to-SQL Azure Harness
-- Idempotent: uses IF NOT EXISTS checks so re-runs are safe
-- Target: Azure SQL Database (T-SQL)
-- ============================================================================

-- Table: customers
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[customers]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[customers] (
        customer_id   INT            IDENTITY(1,1) NOT NULL,
        first_name    NVARCHAR(100)  NOT NULL,
        last_name     NVARCHAR(100)  NOT NULL,
        email         NVARCHAR(255)  NOT NULL,
        phone         NVARCHAR(20)   NULL,
        segment       NVARCHAR(50)   NULL,
        region        NVARCHAR(100)  NULL,
        created_at    DATETIME2      DEFAULT GETUTCDATE(),
        CONSTRAINT PK_customers PRIMARY KEY (customer_id),
        CONSTRAINT UQ_customers_email UNIQUE (email)
    );
END
GO

-- Table: products
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[products]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[products] (
        product_id    INT            IDENTITY(1,1) NOT NULL,
        name          NVARCHAR(200)  NOT NULL,
        category      NVARCHAR(100)  NULL,
        sub_category  NVARCHAR(100)  NULL,
        brand         NVARCHAR(100)  NULL,
        cost_price    DECIMAL(10,2)  NULL,
        list_price    DECIMAL(10,2)  NOT NULL,
        CONSTRAINT PK_products PRIMARY KEY (product_id)
    );
END
GO

-- Table: orders (depends on customers)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[orders]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[orders] (
        order_id      INT            IDENTITY(1,1) NOT NULL,
        customer_id   INT            NOT NULL,
        order_date    DATETIME2      DEFAULT GETUTCDATE(),
        status        NVARCHAR(20)   DEFAULT 'pending',
        total_amount  DECIMAL(12,2)  NULL,
        discount      DECIMAL(10,2)  NULL,
        channel       NVARCHAR(50)   NULL,
        CONSTRAINT PK_orders PRIMARY KEY (order_id),
        CONSTRAINT FK_orders_customer FOREIGN KEY (customer_id)
            REFERENCES [dbo].[customers](customer_id)
    );
END
GO

-- Table: order_items (depends on orders, products)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[order_items]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[order_items] (
        item_id       INT            IDENTITY(1,1) NOT NULL,
        order_id      INT            NOT NULL,
        product_id    INT            NOT NULL,
        quantity      INT            NOT NULL,
        unit_price    DECIMAL(10,2)  NOT NULL,
        line_total    DECIMAL(12,2)  NULL,
        CONSTRAINT PK_order_items PRIMARY KEY (item_id),
        CONSTRAINT FK_order_items_order FOREIGN KEY (order_id)
            REFERENCES [dbo].[orders](order_id),
        CONSTRAINT FK_order_items_product FOREIGN KEY (product_id)
            REFERENCES [dbo].[products](product_id)
    );
END
GO

-- Table: campaigns
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[campaigns]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[campaigns] (
        campaign_id   INT            IDENTITY(1,1) NOT NULL,
        name          NVARCHAR(200)  NOT NULL,
        channel       NVARCHAR(50)   NULL,
        start_date    DATE           NOT NULL,
        end_date      DATE           NULL,
        budget        DECIMAL(12,2)  NULL,
        spend         DECIMAL(12,2)  NULL,
        CONSTRAINT PK_campaigns PRIMARY KEY (campaign_id)
    );
END
GO

-- Table: campaign_conversions (depends on campaigns, customers, orders)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[campaign_conversions]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[campaign_conversions] (
        conversion_id   INT          IDENTITY(1,1) NOT NULL,
        campaign_id     INT          NOT NULL,
        customer_id     INT          NOT NULL,
        order_id        INT          NULL,
        conversion_date DATETIME2    DEFAULT GETUTCDATE(),
        CONSTRAINT PK_campaign_conversions PRIMARY KEY (conversion_id),
        CONSTRAINT FK_conversions_campaign FOREIGN KEY (campaign_id)
            REFERENCES [dbo].[campaigns](campaign_id),
        CONSTRAINT FK_conversions_customer FOREIGN KEY (customer_id)
            REFERENCES [dbo].[customers](customer_id),
        CONSTRAINT FK_conversions_order FOREIGN KEY (order_id)
            REFERENCES [dbo].[orders](order_id)
    );
END
GO

-- Table: support_tickets (depends on customers, orders)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[support_tickets]') AND type = N'U')
BEGIN
    CREATE TABLE [dbo].[support_tickets] (
        ticket_id     INT            IDENTITY(1,1) NOT NULL,
        customer_id   INT            NOT NULL,
        order_id      INT            NULL,
        category      NVARCHAR(100)  NULL,
        priority      NVARCHAR(10)   DEFAULT 'medium',
        status        NVARCHAR(20)   DEFAULT 'open',
        created_at    DATETIME2      DEFAULT GETUTCDATE(),
        resolved_at   DATETIME2      NULL,
        CONSTRAINT PK_support_tickets PRIMARY KEY (ticket_id),
        CONSTRAINT FK_tickets_customer FOREIGN KEY (customer_id)
            REFERENCES [dbo].[customers](customer_id),
        CONSTRAINT FK_tickets_order FOREIGN KEY (order_id)
            REFERENCES [dbo].[orders](order_id)
    );
END
GO
