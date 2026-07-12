CREATE CONSTRAINT seller_id IF NOT EXISTS FOR (n:Seller) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
CREATE CONSTRAINT program_id IF NOT EXISTS FOR (n:Program) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
CREATE CONSTRAINT fee_id IF NOT EXISTS FOR (n:Fee) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
CREATE CONSTRAINT policy_id IF NOT EXISTS FOR (n:Policy) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
CREATE CONSTRAINT region_id IF NOT EXISTS FOR (n:Region) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
CREATE CONSTRAINT eligibility_rule_id IF NOT EXISTS FOR (n:EligibilityRule) REQUIRE (n.tenant_id, n.id) IS UNIQUE;
