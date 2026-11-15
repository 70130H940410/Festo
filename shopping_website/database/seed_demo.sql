-- Entirely synthetic fixtures. dev.py attaches only the new products/orders databases.
BEGIN;
INSERT INTO products.products (id,name,description,base_price,stock) VALUES
 (1,'Basic Fuse Box - Black','協作測試商品：黑色；非實際庫存',100,50),
 (2,'Basic Fuse Box - Blue','協作測試商品：藍色；非實際庫存',110,50),
 (3,'Basic Fuse Box - White','協作測試商品：白色；非實際庫存',120,50);
INSERT INTO products.raw_materials (id,name,stock) VALUES
 (1,'測試黑色上蓋',200),(2,'測試藍色上蓋',200),(3,'測試白色上蓋',200),
 (4,'測試下蓋',600),(5,'測試 PCB',600),(6,'測試保險絲',1200);
INSERT INTO products.bom VALUES
 (1,1,1),(1,4,1),(1,5,1),(1,6,2),
 (2,2,1),(2,4,1),(2,5,1),(2,6,2),
 (3,3,1),(3,4,1),(3,5,1),(3,6,2);
INSERT INTO products.product_name SELECT name,stock FROM products.products;
INSERT INTO products.standard_process (id,step_order,step_name,station,description,estimated_time_sec) VALUES
 (1,1,'訂單與供料','ASRS 自動倉儲 (Stopper 1 / A1)','本機模擬出料',5),
 (2,2,'尺寸量測','尺寸量測 (Station B / B)','本機模擬尺寸檢測',5),
 (3,3,'鑽孔','鑽孔 (Station C / C)','本機模擬單次鑽孔',5),
 (4,4,'PCB 組裝','機器人室 (Station D / D)','本機模擬組裝',8),
 (5,5,'視覺檢測','視覺檢測 (Station E / E)','本機模擬檢測',5),
 (6,6,'放置下蓋','盒匣 (Station F / F)','本機模擬下蓋供料',5),
 (7,7,'上下蓋壓合','氣壓壓製 (Station G / G)','本機模擬單次壓合',5),
 (8,8,'膠合固化','烘烤加熱 (Station H / H)','本機模擬加熱',8),
 (9,9,'成品入庫','ASRS 自動倉儲 (Stopper 2 / A2)','本機模擬入庫',5);
INSERT INTO orders.order_list
 (order_id,date,customer_name,product,amount,total_price,step_name,note,status,estimated_delivery,priority,
  contact_name,contact_phone,company,address,source)
VALUES
 ('DEMO-BLACK-001',datetime('now','localtime','-2 hours'),'demo_customer','Basic Fuse Box - Black x 2',2,200,
  '1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9','離線範例：黑色完整製程，非 MES 工單','active',
  datetime('now','localtime','+1 day'),1,'測試使用者','TEST-ONLY','協作範例','不配送','demo'),
 ('DEMO-BLUE-002',datetime('now','localtime','-1 hour'),'demo_customer','Basic Fuse Box - Blue x 1',1,110,
  '1 -> 9','離線範例：藍色出入庫，尚未付款','pending_payment',
  datetime('now','localtime','+2 days'),0,'測試使用者','TEST-ONLY','協作範例','不配送','demo'),
 ('DEMO-WHITE-003',datetime('now','localtime','-1 day'),'demo_customer','Basic Fuse Box - White x 1',1,120,
  '1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9','離線範例：已完成，不代表實廠紀錄','completed',
  datetime('now','localtime','-1 hour'),0,'測試使用者','TEST-ONLY','協作範例','不配送','demo');
INSERT INTO orders.factory_state(id) VALUES(1);
INSERT INTO orders.station_state(station) SELECT DISTINCT station FROM products.standard_process;
INSERT INTO orders.station_jobs(step_order) SELECT step_order FROM products.standard_process;
INSERT INTO orders.piece_step_progress(order_id,piece_no,step_order,state)
 SELECT 'DEMO-BLACK-001',piece_no,step_order,'pending'
 FROM (SELECT 1 AS piece_no UNION ALL SELECT 2) CROSS JOIN products.standard_process;
INSERT INTO orders.piece_step_progress(order_id,piece_no,step_order,state)
 VALUES('DEMO-BLUE-002',1,1,'pending'),('DEMO-BLUE-002',1,9,'pending');
INSERT INTO orders.piece_step_progress(order_id,piece_no,step_order,state,started_at,finished_at)
 SELECT 'DEMO-WHITE-003',1,step_order,'finished',
 datetime('now','localtime','-2 hours'),datetime('now','localtime','-1 hour') FROM products.standard_process;
COMMIT;
