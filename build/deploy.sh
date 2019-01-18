#! /bin/bash
stack_name="JobCreator"
stack=$(aws cloudformation describe-stacks --stack-name $stack_name --query Stacks[0].StackName --output text)

if [ -z "$stack" ]
then
      echo "$stack_name does not exist, creating..."
      aws cloudformation create-stack --stack-name $stack_name --template-body file://cloudformation/jobcreator.yml
      echo "Waiting on stack to create..."
      aws cloudformation wait stack-create-complete --stack-name $stack_name
      echo "Stack created."
else
      echo "$stack_name does exist, updating..."
      aws cloudformation update-stack --stack-name $stack_name --template-body file://cloudformation/jobcreator.yml
      if [[ $? != 0 ]]; then exit $?; fi
      echo "Waiting on stack to update..."
      aws cloudformation wait stack-update-complete --stack-name $stack_name
      echo "Stack updated."
fi