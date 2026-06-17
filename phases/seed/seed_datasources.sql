INSERT INTO eivs.datasources (datasource_id, name, datasourcetype, connectionkey, semanticmodelyaml, isactive)
VALUES 
(uuid_generate_v4(), 'LoanDB', 'postgres', 'postgresql://postgres:postgres@db:5432/loandb', 'config/semantic_model_yaml/loan.yaml', true);
