from flask import Flask,render_template,Response
from EMonitorDB import EMonitorDBReader


db=EMonitorDBReader()

db.load_latest()

app=Flask(__name__)

@app.route('/')
def current():
  current_power=db.load_latest()
  rows=[]
  for circuit in current_power:
    row_vals={}
    row_vals['id']=circuit.get('id',0)
    row_vals['name']=circuit.get('name','NA')
    row_vals['power']=circuit.get('power',0)
    rows.append(row_vals)
  return render_template('/current.html',data=rows)

if __name__ == '__main__':
    app.run()