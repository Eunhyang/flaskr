import subprocess, boto3, random
from celery import Celery
from flask import Flask, render_template, request

app = Flask(__name__)
def make_celery(app):
    celery = Celery(app.import_name, backend=app.config['CELERY_RESULT_BACKEND'],
                    broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery

app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379',
    CELERY_RESULT_BACKEND='redis://localhost:6379'
)
celery = make_celery(app)

@celery.task()
def ceate_instance(text):
    with open('./sample/app.py', 'r') as file:
        filedata = file.read()

    filedata = filedata.replace("here", text)

    with open('./sample/app.py', 'w') as file:
        file.write(filedata)

    instance_name = "aws-randombox-%032x" % random.getrandbits(128)
    subprocess.call(["docker-machine", "create", "--driver",
                     "amazonec2", "--amazonec2-open-port", "4000", "--amazonec2-region",
                     "ap-northeast-2", "--amazonec2-vpc-id", "vpc-e3db2a8a",
                     "--amazonec2-subnet-id", "subnet-ded625b7", instance_name])
    subprocess.check_output('docker-machine scp -r -d sample/ {}:/home/ubuntu/'.format(instance_name), shell=True)
    subprocess.check_output('docker-machine ssh {} "sudo docker build -t friendlyhello ."'.format(instance_name), shell=True)
    subprocess.check_output('docker-machine ssh {} "sudo docker run -p 4000:80 friendlyhello"'.format(instance_name),
                            shell=True)
    ip = subprocess.check_output('docker-machine ip {}'.format(instance_name), shell=True)
    return ip

@app.route('/')
def index():

    docker_machines_output = subprocess.check_output('docker-machine ls --format "{{.Name}},{{.URL}}"', shell=True)
    texts = docker_machines_output.decode('ascii').split('\n')
    docker_machines = []
    for text in texts:
        if not len(text):
            continue
        else:
            temp = text.split(',')
            docker_machines.append({'name': temp[0], 'ip': temp[1]})

    for i, docker in enumerate(docker_machines):
        docker_containers = subprocess.check_output('docker-machine ssh %s "sudo docker container ls --format "{{.ID}}""'% (docker['name']), shell=True)
        docker_containers =  docker_containers.decode('ascii').split('\n')
        docker_containers = list(filter(None, docker_containers))
        docker_machines[i].update({'containers':docker_containers})

    ec2 = boto3.client('ec2')
    response = ec2.describe_instances()
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            for i, docker in enumerate(docker_machines):
                if instance['KeyName'] == docker['name']:
                    group_id = instance['SecurityGroups'][0]['GroupId']
                    ip_permissions = ec2.describe_security_groups(GroupIds=[group_id])['SecurityGroups'][0]['IpPermissions']
                    docker.update({'ip_permissions':str(ip_permissions)})

    return render_template('index.html', docker_machines = docker_machines)

@app.route('/result', methods=['GET', 'POST'])
def result():
    if request.method == 'POST':
        text = request.form['text']
        ceate_instance.delay(text)
    return render_template('result.html')


if __name__ == '__main__':
    app.run()