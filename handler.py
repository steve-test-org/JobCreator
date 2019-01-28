import json
import base64
import boto3
import yaml
from github import Github, GithubException
from botocore.exceptions import ClientError

THIS_REPO = 'JobCreator'
STACK_PREFIX = 'Pipeline'


def job_creator(event, context):

    manager = PipelineManager(
        org_name='steve-test-org',
        git_token_path='/JobCreator/Github_OAuth',
        artefact_bucket='s3-sjp-testing')

    manager.run()


class PipelineManager():

    def __init__(self, org_name, git_token_path, artefact_bucket):
        self.org_name = org_name
        self.artefact_bucket = artefact_bucket

        self.ssm_client = boto3.client('ssm')
        self.cfn_client = boto3.client('cloudformation')

        self.github_token = self.ssm_client.get_parameter(Name=git_token_path)['Parameter']['Value']

        git = Github(self.github_token)
        self.org = git.get_organization(org_name)

        self.repos = self.org.get_repos()

    @staticmethod
    def get_contents(repo, file_path, ref='master'):
        try:
            contents = repo.get_contents(file_path, ref)
        except GithubException:
            return None

        return contents

    def run(self):
        for repo in self.repos:
            if repo.name == THIS_REPO:
                continue

            self.process_repo(repo)

    def process_repo(self, repo):
        contents = PipelineManager.get_contents(repo, 'deploy-config.yml')

        if not contents:
            print(f'Could not find config for {repo.name}, skipping.')
            return

        if contents.encoding == 'base64':
            config = yaml.safe_load(base64.b64decode(contents.content).decode('utf-8'))

        if 'Environments' not in config:
            print(f'Could not find environments block inconfig for {repo.name}, skipping.')
            return

        actual_stacks = self.get_existing_stacks(self.cfn_client)

        stacks_to_create = {k: v for k, v in config['Environments'].items(
        ) if self.get_stack_name(repo.name, k) not in actual_stacks}

        stacks_to_update = {k: v for k, v in config['Environments'].items(
        ) if self.get_stack_name(repo.name, k) in actual_stacks}

        stacks_to_delete = [s for s in actual_stacks if self.get_env_from_stack_name(s) not in config['Environments']]

        for env_name, config in stacks_to_create.items():
            self.create_stack(repo, env_name, config)

        for env_name, config in stacks_to_update.items():
            self.update_stack(repo, env_name, config)

        for stack_name in stacks_to_delete:
            self.delete_stack(stack_name)
            print(f'Should delete resources created by {self.get_env_from_stack_name(stack_name)}')

    @staticmethod
    def get_stack_name(repo_name, env_name):
        return f'{STACK_PREFIX}-{repo_name}-{env_name}'

    @staticmethod
    def get_env_from_stack_name(stack_name):
        return stack_name.split('-')[-1]

    def get_existing_stacks(self, client):

        stacks = []
        paginator = client.get_paginator('list_stacks')
        page_iterator = paginator.paginate()

        for page in page_iterator:
            for stack in page['StackSummaries']:
                if stack['StackStatus'] != 'DELETE_COMPLETE' and stack['StackName'].startswith(STACK_PREFIX):
                    stacks.append(stack['StackName'])

        return stacks

    def create_stack(self, repo, env_name, config):

        body = self.get_template_body(repo, config['source'])

        response = self.cfn_client.create_stack(
            StackName=self.get_stack_name(repo.name, env_name),
            TemplateBody=body,
            Parameters=self.get_params(repo, env_name, config),
            TimeoutInMinutes=60,
            Capabilities=[
                'CAPABILITY_IAM'
            ]
        )
        print(response)

    def get_params(self, repo, env_name, config):
        return [{'ParameterKey': 'ArtifactBucket', 'ParameterValue': self.artefact_bucket, },
                {'ParameterKey': 'GitHubToken', 'ParameterValue': self.github_token, },
                {'ParameterKey': 'AccountID', 'ParameterValue': str(config['account']), },
                {'ParameterKey': 'EnvironmentName', 'ParameterValue': env_name, },
                {'ParameterKey': 'Organisation', 'ParameterValue': self.org_name, },
                {'ParameterKey': 'Branch', 'ParameterValue': config['source'], },
                {'ParameterKey': 'Repository', 'ParameterValue': repo.name, },
                {'ParameterKey': 'ArtifactBucket', 'ParameterValue': self.artefact_bucket, }]

    def update_stack(self, repo, env_name, config):
        body = self.get_template_body(repo, config['source'])
        stack_name = self.get_stack_name(repo.name, env_name)

        try:
            response = self.cfn_client.update_stack(
                StackName=stack_name,
                TemplateBody=body,
                Parameters=self.get_params(repo, env_name, config),
                Capabilities=['CAPABILITY_IAM']
            )
            print(response)
        except ClientError as e:
            if e.response['Error']['Message'] == 'No updates are to be performed.':
                print(f'No updates are required for {stack_name}.')
            else:
                raise

    def delete_stack(self, stack_name):
        print(f'Removing {stack_name}')
        response = self.cfn_client.delete_stack(StackName=stack_name)
        print(response)

    @staticmethod
    def get_template_body(repo, branch_name):

        try:
            contents = PipelineManager.get_contents(
                repo, 'pipeline.yml', branch_name)

            if contents.encoding == 'base64':
                body = base64.b64decode(contents.content).decode('utf-8')
        except GithubException:
            print('TODO - use default file in cloudformation/pipeline.yml')
            raise

        return body


# job_creator(None, None)
