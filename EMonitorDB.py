import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base

Base= declarative_base()

class RawData(Base):
  __tablename__ = 'raw_data'
  time = sqlalchemy.Column(sqlalchemy.DateTime, primary_key=True)
  channel = sqlalchemy.Column(sqlalchemy.String(length=20), primary_key=True)
  power = sqlalchemy.Column(sqlalchemy.Integer)

  def __repr__(self):
    return f'<raw_data(time={self.time}, channel={self.channel}, power={self.power}'



class EMonitorDB:
  def __init__(self):
    self.host_="localhost"
    self.engine_ = sqlalchemy.create_engine(
      'mysql+mysqlconnector://writer:writer@localhost:3306/emonitor',
      echo=True)
    Base.metadata.create_all(self.engine_)
